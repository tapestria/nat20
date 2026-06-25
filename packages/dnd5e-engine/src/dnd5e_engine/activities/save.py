"""``save`` kind handler for the Activity resolver.

A Foundry ``SaveActivity`` (``save-data.mjs``) makes each target roll a saving
throw vs a DC; ``damage.on_save`` ("half"/"none"/"full") scales the rolled damage
on a SUCCESS. Canonical SRD 5.2 examples: Fireball (8d6 fire, Dex save, half on
save) and Flame Strike (5d6 fire + 5d6 radiant, Dex save, half on save).

CRITICAL on-save semantics (a plan-review finding): the on_save scaling is
applied PER PART, before the parts are summed into per-type buckets. A multi-
typed save spell (Flame Strike: 5d6 fire + 5d6 radiant; Ice Storm: 2d10
bludgeoning + 4d6 cold) halves EACH typed part independently — never the summed
total. Halving the summed total would mis-distribute the rounding across types.

CRITICAL roll-once semantics (a cross-model review finding): a multi-target save
spell rolls its DAMAGE exactly ONCE; every affected target takes the SAME rolled
result, then scales by ITS OWN save outcome (fail → full, success → on_save). The
damage parts are therefore rolled BEFORE the per-target loop (``_roll_shared_damage``)
and the shared raw amounts are reused for every target. Only the d20 SAVE roll is
per-target — each target rolls its own save. Rerolling the damage per target was a
bug: two failed targets of one Fireball must take the IDENTICAL 8d6, not two rolls.

MIRRORS, does not import from, ``effects/save.py`` + ``effects/damage.py``:

* DC resolution mirrors ``effects/save.py:_resolve_dc`` — a missing/empty DC
  raises ``ValueError`` (loud), never silently defaults. The two SRD-2024 DC
  calculations Foundry ships are ``"spellcasting"``
  (``8 + prof + spellcasting-ability mod``) and ``"flat"`` (the parsed
  ``save.dc.formula``); any other ``calculation`` raises.
* The natural save d20 + the per-ability modifier + the ``total >= dc``
  comparison live in the shared ``activities/save_primitive.py:roll_save`` (also
  used by weapon-mastery topple). The d20 honors ``ctx.variables["force_save_d20"]``
  (a NEW test seam — ``effects/save.py`` has none) for the FIRST target only; the
  modifier is sourced exactly as ``effects/save.py:_read_save_modifier`` does — the
  RESOLVED per-ability integer off a per-target sidecar (there:
  ``effect_store._save_modifiers[id]["saves"]``; here: ``ctx.passive_save_modifiers[id]``),
  NOT rebuilt from ability score + proficiency. ``Combatant`` carries no per-
  ability save table, so an absent target / ability contributes +0 (mirrors the
  0 fallback). This handler emits ``SaveRolled`` per target around the primitive.
* Per-part dice rolling + cantrip/upcast scaling wiring mirrors
  ``activities/damage.py`` (``character_level=ctx.caster_level``,
  ``slot_level=ctx.slot_level``, ``base_level=ctx.base_spell_level``); target-
  side vuln/resist/immune + ``DamageApplied`` emission run through ``apply.py``.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import TYPE_CHECKING, Final, get_args

from dnd5e_engine.activities.apply import apply_damage
from dnd5e_engine.activities.dice import roll_damage_part, roll_expr
from dnd5e_engine.activities.effects import apply_activity_effects
from dnd5e_engine.activities.formula import resolve_damage_block, resolve_roll_data
from dnd5e_engine.activities.save_primitive import roll_save
from dnd5e_engine.events import Ability, SaveRolled

if TYPE_CHECKING:
    from dnd5e_srd_data.schema.common import DamagePartBlock, SaveActivity

    from dnd5e_engine.types.combat import Combatant

    from .context import ActivityResolutionContext

_LOGGER = logging.getLogger(__name__)

# The closed set of SRD ability codes, sourced from the Ability Literal so the
# validation and the event field never drift.
_ABILITIES: Final[frozenset[str]] = frozenset(get_args(Ability))


def resolve_save(activity: SaveActivity, ctx: ActivityResolutionContext) -> None:
    """Roll a saving throw per target, then apply on-save-scaled damage.

    DC and save ability are computed once (they do not vary per target). The
    DAMAGE roll is ALSO rolled ONCE (SRD: a multi-target save spell — Fireball,
    Flame Strike — rolls its damage once; every affected target takes the SAME
    rolled result, then scales by ITS OWN save outcome). Only the d20 SAVE roll is
    per-target. For each target: roll the natural save d20, add the target's save
    modifier, emit ``SaveRolled``, then scale each SHARED per-part raw amount by
    ``on_save`` on a success, accumulate into per-type buckets, and apply. Each
    target's effect riders fire AFTER its damage, gated on that target's own save
    outcome (``EffectApplied`` then ``ConditionApplied``).
    """
    dc = _resolve_dc(activity, ctx)
    ability = _resolve_save_ability(activity)
    cast_level = ctx.slot_level or ctx.base_spell_level or 0

    # Roll the damage parts ONCE, BEFORE the per-target d20 loop. Each affected
    # target shares this single roll; per-target divergence comes only from the
    # save outcome (fail → full, success → on_save policy), never a reroll.
    shared_parts = _roll_shared_damage(activity, ctx)

    for index, target in enumerate(ctx.targets):
        total, succeeded = roll_save(ctx, target, ability, dc, target_index=index)

        ctx.event_emitter(
            SaveRolled(
                target_id=target.entity_id,
                ability=ability,
                dc=dc,
                roll_total=total,
                succeeded=succeeded,
            )
        )

        _apply_save_damage(activity, ctx, target, shared_parts, succeeded=succeeded)
        apply_activity_effects(
            activity, ctx, target, save_succeeded=succeeded, cast_level=cast_level
        )


# ── DC + ability resolution ──────────────────────────────────────────────────


def _resolve_dc(activity: SaveActivity, ctx: ActivityResolutionContext) -> int:
    """Resolve ``save.dc`` to a concrete int per ``save.dc.calculation``.

    * ``"spellcasting"`` → ``8 + prof + ability_mod(spellcasting_ability)`` (SRD
      §Spellcasting — Spell Save DCs). Requires a caster spellcasting ability;
      absent → ``ValueError`` (via ``ctx.ability_mod`` reading no score is fine,
      but the calculation is meaningless without one, so guard explicitly).
    * ``"flat"`` → the parsed ``save.dc.formula`` (@-tokens resolved, folded off
      the seeded rng); a flat DC carries no dice in the SRD corpus.
    * empty / unknown ``calculation`` → ``ValueError`` (loud; mirrors
      ``effects/save.py:_resolve_dc`` raising rather than silently defaulting).

    A cast wrapper's fixed challenge override (``ctx.save_dc_override``) bypasses
    the calculation entirely — a scroll/item DC (Dragon Orb 18) is used verbatim.
    """
    if ctx.save_dc_override is not None:
        return ctx.save_dc_override
    calculation = activity.save.dc.calculation
    if calculation == "spellcasting":
        if ctx.spellcasting_ability is None:
            raise ValueError(
                "save.dc.calculation == 'spellcasting' requires a caster "
                "spellcasting ability but the context supplies none"
            )
        return 8 + ctx.caster_proficiency_bonus + ctx.ability_mod(ctx.spellcasting_ability)
    if calculation == "flat":
        resolved = resolve_roll_data(
            activity.save.dc.formula, ctx, ability=ctx.spellcasting_ability
        )
        return roll_expr(resolved, ctx.rng)
    raise ValueError(
        f"save.dc.calculation {calculation!r} is not resolvable "
        f"(expected 'spellcasting' or 'flat'); refusing to default a save DC silently"
    )


def _resolve_save_ability(activity: SaveActivity) -> Ability:
    """The single SRD ability the save is made against.

    SRD saves are single-ability; Foundry stores ``save.ability`` as a list. The
    first entry is used and validated against the closed Ability set. An empty
    list (ill-formed data) raises rather than defaulting.
    """
    abilities = activity.save.ability
    if not abilities:
        raise ValueError("save.ability is empty; a SaveActivity must name a saving-throw ability")
    first = abilities[0]
    if first not in _ABILITIES:
        raise ValueError(
            f"save.ability[0] {first!r} is not a valid SRD ability code "
            f"(expected one of {sorted(_ABILITIES)})"
        )
    return first  # type: ignore[return-value]


# ── on-save-scaled damage ────────────────────────────────────────────────────


def _roll_shared_damage(
    activity: SaveActivity, ctx: ActivityResolutionContext
) -> list[tuple[str, int]]:
    """Roll ``damage.parts`` ONCE into ``(damage_type, raw_amount)`` pairs.

    Each part is rolled in declaration order off ``ctx.rng`` (cantrip/upcast
    scaling wired like ``activities/damage.py``); typeless/skipped parts are
    dropped here exactly as before. The result is the SHARED roll handed to every
    target — the SRD roll-once semantics for a multi-target save spell. Pairs (not
    a dict) preserve declaration order AND keep distinct-type parts separable so
    each target can scale per part before summing into its own per-type bucket.
    """
    parts: list[tuple[str, int]] = []
    for part in activity.damage.parts:
        damage_type = _part_type(part, activity.id, ctx)
        if damage_type is None:
            continue
        resolved = resolve_damage_block(part, ctx, ability=ctx.spellcasting_ability)
        raw_part = roll_damage_part(
            resolved,
            ctx.rng,
            crit=False,
            character_level=ctx.caster_level,
            slot_level=ctx.slot_level,
            base_level=ctx.base_spell_level,
        )
        parts.append((damage_type, raw_part))
    return parts


def _apply_save_damage(
    activity: SaveActivity,
    ctx: ActivityResolutionContext,
    target: Combatant,
    shared_parts: list[tuple[str, int]],
    *,
    succeeded: bool,
) -> None:
    """Scale the SHARED per-part raw amounts by ``on_save`` for ``target``, apply.

    The parts are pre-rolled ONCE (``_roll_shared_damage``) so every target shares
    the identical base roll. On a SUCCESS each part's raw amount is scaled by
    ``on_save`` BEFORE being added to its per-type bucket: "half" → ``raw // 2``,
    "none" → 0, "full" → ``raw``. On a FAILURE every part is full. The scaled
    per-type buckets are then handed to ``apply.apply_damage`` (one ``DamageApplied``
    per type, after this target's own vuln/resist/immune).
    """
    by_type: dict[str, int] = defaultdict(int)
    for damage_type, raw_part in shared_parts:
        by_type[damage_type] += _scale_on_save(
            raw_part, activity.damage.on_save, succeeded=succeeded
        )

    apply_damage(target, dict(by_type), ctx)


def _scale_on_save(raw_part: int, on_save: str, *, succeeded: bool) -> int:
    """Per-part on-save scaling. Failure → full; success → on_save policy.

    "half" → ``raw // 2`` (SRD half-damage rounds down). "none" → 0. "full" →
    ``raw`` (a few SRD spells deal full damage even on a save). An unknown
    ``on_save`` is logged loudly and treated as "full" (no silent zeroing).
    """
    if not succeeded:
        return raw_part
    if on_save == "half":
        return raw_part // 2
    if on_save == "none":
        return 0
    if on_save == "full":
        return raw_part
    _LOGGER.warning("save_on_save_unknown on_save=%s; treating as full", on_save)
    return raw_part


def _part_type(
    part: DamagePartBlock, activity_id: str, ctx: ActivityResolutionContext
) -> str | None:
    """The single damage type a save-damage part applies as.

    Mirrors ``activities/damage.py:_part_type``: a single-type part applies as
    that type; a multi-type CHOICE part (e.g. Spirit Guardians' [necrotic,
    radiant]) resolves ``ctx.damage_type_choices`` (or defaults to the first,
    logged at INFO); a typeless part (a data defect) is logged and skipped.
    """
    if not part.types:
        _LOGGER.warning(
            "damage_part_untyped activity_id=%s denomination=%s number=%s",
            activity_id,
            part.denomination,
            part.number,
        )
        return None
    if len(part.types) == 1:
        return part.types[0]

    chosen = ctx.damage_type_choices.get(activity_id)
    if chosen is not None and chosen in part.types:
        return chosen
    if chosen is not None:
        _LOGGER.warning(
            "damage_type_choice_invalid activity_id=%s chose=%s options=%s",
            activity_id,
            chosen,
            part.types,
        )
    _LOGGER.info(
        "damage_type_defaulted activity_id=%s chose=%s options=%s",
        activity_id,
        part.types[0],
        part.types,
    )
    return part.types[0]
