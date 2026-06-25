"""``check`` kind handler for the Activity resolver.

A Foundry ``CheckActivity`` (``check-data.mjs``) makes ONE actor roll a d20-based
ability or skill check against a DC, then applies its effect riders. Canonical
SRD 5.2 examples: Maze's "Banish to Maze" (Intelligence/investigation check vs DC
20 to escape) and manacles' "Escape Check" / "Burst Check" (sleight-of-hand /
athletics vs a flat DC).

Unlike a ``save``, a check CAN carry no DC at all. A no-DC check is purely
informational: the actor still rolls, ``CheckRolled`` is still emitted, but
``succeeded`` is ``None`` (no pass/fail comparison is made).

MIRRORS, does not import from, ``effects/check.py``:

* The ACTOR that rolls is the activity's first TARGET when one is present (an
  imposed check — escape the manacles, resist Banish to Maze), exactly as
  ``effects/check.py`` rolls for ``ctx.target_list[0]``. With no target the
  CASTER rolls (a self-check — a PC's own Stealth check). Contested checks (a
  second, opposed caster roll) are out of Piece-1-2 scope.
* The skill→ability mapping mirrors ``effects/check.py:_SKILL_TO_ABILITY`` but is
  keyed by the Foundry 3-letter skill *codes* the canonical ``check.associated``
  field actually carries (``"ath"``, ``"slt"``, ``"inv"``, ...) rather than the
  Avrae long-form (``"athletics"``). Source: ``CONFIG.DND5E.skills`` in
  ``foundry/module/config.mjs``.
* The modifier is the RESOLVED integer off a per-actor sidecar
  (``ctx.check_modifiers``), mirroring ``effects/check.py:_read_check_modifiers``
  / ``_modifier_for_key`` — the skill mod (``skills[code]``) when a skill is
  named, else the ability mod (``ability_mods[ability]``), else +0. ``Combatant``
  carries no per-skill table, so the value comes from the sidecar.
* The DC resolution mirrors Foundry ``check-data.mjs`` prepareFinalData
  (lines 65-69): ``"spellcasting"`` → ``8 + prof + spellcasting-ability mod``;
  ``"flat"`` → the parsed ``check.dc.formula``; an EMPTY calculation falls back
  to the flat ``formula`` when one is present (Foundry's ``simplifyBonus(formula)``
  branch — every real canonical check ships ``calculation=""`` + a literal
  formula), and resolves to ``None`` only when calculation AND formula are both
  empty.

The natural d20 honors ``ctx.variables["force_check_d20"]`` — a NEW test seam
(our own; ``effects/check.py`` relies on a seeded ``ctx.rng``). Riders fire AFTER
the roll via the shared ``apply_activity_effects`` (``EffectApplied`` then
``ConditionApplied``), applied to the rolling actor.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Final, get_args

from dnd5e_engine.activities.dice import roll_expr
from dnd5e_engine.activities.effects import apply_activity_effects
from dnd5e_engine.activities.formula import resolve_roll_data
from dnd5e_engine.events import Ability, CheckRolled

if TYPE_CHECKING:
    from dnd5e_srd_data.schema.common import CheckActivity

    from dnd5e_engine.types.combat import Combatant

    from .context import ActivityResolutionContext

_LOGGER = logging.getLogger(__name__)

# The closed set of SRD ability codes, sourced from the Ability Literal so the
# validation and the event field never drift.
_ABILITIES: Final[frozenset[str]] = frozenset(get_args(Ability))

# Foundry 3-letter skill code → governing SRD ability. Source: CONFIG.DND5E.skills
# in foundry/module/config.mjs (each skill's ``ability`` field). The canonical
# ``check.associated`` field carries these codes verbatim. Mirrors
# ``effects/check.py:_SKILL_TO_ABILITY`` (which keys the Avrae long-form names).
_SKILL_TO_ABILITY: Final[dict[str, Ability]] = {
    "acr": "dex",
    "ani": "wis",
    "arc": "int",
    "ath": "str",
    "dec": "cha",
    "his": "int",
    "ins": "wis",
    "itm": "cha",
    "inv": "int",
    "med": "wis",
    "nat": "int",
    "prc": "wis",
    "prf": "cha",
    "per": "cha",
    "rel": "int",
    "slt": "dex",
    "ste": "dex",
    "sur": "wis",
}

# Test-determinism seam for the natural check d20 (our own code; effects/check.py
# has none and relies on a seeded ctx.rng).
FORCE_CHECK_D20: Final = "force_check_d20"


def resolve_check(activity: CheckActivity, ctx: ActivityResolutionContext) -> None:
    """Roll one ability/skill check, emit ``CheckRolled``, apply effect riders.

    The DC is resolved once (it may be ``None`` for an informational check). One
    actor — the first target when present, else the caster — rolls a natural d20
    (honoring ``force_check_d20``) plus its skill-or-ability modifier off
    ``ctx.check_modifiers``. ``succeeded`` is ``total >= dc`` (or ``None`` when
    there is no DC). The activity's effect riders then fire on that actor.
    """
    dc = _resolve_dc(activity, ctx)
    skill, ability = _resolve_skill_ability(activity)
    actor = ctx.targets[0] if ctx.targets else ctx.caster

    natural = _roll_d20(ctx)
    modifier = _check_modifier(ctx, actor, skill=skill, ability=ability)
    total = natural + modifier
    succeeded = (total >= dc) if dc is not None else None

    ctx.event_emitter(
        CheckRolled(
            actor_id=actor.entity_id,
            ability=ability,
            skill=skill,
            dc=dc,
            roll_total=total,
            succeeded=succeeded,
        )
    )

    # Riders apply to the rolling actor (e.g. manacles "Bind" → Restrained on the
    # bound creature). A check carries no save outcome, so the on-save gate is
    # inert (``save_succeeded=None`` applies unconditionally).
    cast_level = ctx.slot_level or ctx.base_spell_level or 0
    apply_activity_effects(activity, ctx, actor, save_succeeded=None, cast_level=cast_level)


# ── DC resolution ─────────────────────────────────────────────────────────────


def _resolve_dc(activity: CheckActivity, ctx: ActivityResolutionContext) -> int | None:
    """Resolve ``check.dc`` to a concrete int, or ``None`` for a no-DC check.

    Mirrors Foundry ``check-data.mjs`` prepareFinalData:

    * ``"spellcasting"`` → ``8 + prof + ability_mod(spellcasting_ability)`` (needs
      a caster spellcasting ability; absent → ``ValueError``).
    * ``"flat"`` → the parsed ``check.dc.formula`` (@-tokens resolved off the
      seeded rng; a flat DC carries no dice in the SRD corpus).
    * EMPTY calculation → the flat ``formula`` when one is present (Foundry's
      ``simplifyBonus(formula)`` branch — every canonical check ships
      ``calculation=""`` + a literal formula); ``None`` only when calculation AND
      formula are BOTH empty (a no-DC informational check).
    * any other calculation → ``ValueError`` (loud; never silently default).
    """
    calculation = activity.check.dc.calculation
    formula = activity.check.dc.formula

    if calculation == "spellcasting":
        if ctx.spellcasting_ability is None:
            raise ValueError(
                "check.dc.calculation == 'spellcasting' requires a caster "
                "spellcasting ability but the context supplies none"
            )
        return 8 + ctx.caster_proficiency_bonus + ctx.ability_mod(ctx.spellcasting_ability)

    if calculation in ("flat", ""):
        if not formula:
            # Empty calculation AND empty formula → a no-DC informational check.
            return None
        resolved = resolve_roll_data(formula, ctx, ability=ctx.spellcasting_ability)
        return roll_expr(resolved, ctx.rng)

    raise ValueError(
        f"check.dc.calculation {calculation!r} is not resolvable "
        f"(expected 'spellcasting', 'flat', or empty)"
    )


def _resolve_skill_ability(activity: CheckActivity) -> tuple[str | None, Ability]:
    """The (skill, ability) the check is rolled with.

    ``check.associated[0]`` (when present) names the skill — a Foundry 3-letter
    code whose governing ability comes from ``_SKILL_TO_ABILITY``. With no
    associated skill (a raw-ability check) the ability is ``check.ability``,
    validated against the closed Ability set. A check naming neither a resolvable
    skill nor an explicit ability cannot be rolled and raises.

    An ``associated`` entry that is NOT a known skill code (a tool slug) falls
    back to the explicit ``check.ability``; the slug is still surfaced as the
    ``CheckRolled.skill`` label.
    """
    associated = activity.check.associated
    skill = associated[0] if associated else None

    if skill is not None and skill in _SKILL_TO_ABILITY:
        return skill, _SKILL_TO_ABILITY[skill]

    # Raw-ability check, or a tool slug whose ability is named explicitly.
    ability = activity.check.ability
    if ability not in _ABILITIES:
        raise ValueError(
            f"check has no resolvable ability: associated={associated!r} "
            f"ability={ability!r} (expected a known skill code or one of "
            f"{sorted(_ABILITIES)})"
        )
    return skill, ability  # type: ignore[return-value]


# ── roll + modifier ───────────────────────────────────────────────────────────


def _roll_d20(ctx: ActivityResolutionContext) -> int:
    """Natural check d20, honoring ``variables["force_check_d20"]``.

    Piece-1-2 scope has no check advantage/disadvantage projection, so a single
    d20 is drawn (off ``ctx.rng`` unless the forced test seam is set).
    """
    forced = ctx.variables.get(FORCE_CHECK_D20)
    if forced is not None:
        return int(forced)
    return ctx.rng.randint(1, 20)


def _check_modifier(
    ctx: ActivityResolutionContext,
    actor: Combatant,
    *,
    skill: str | None,
    ability: str,
) -> int:
    """The actor's resolved check modifier off ``ctx.check_modifiers``.

    Mirrors ``effects/check.py:_modifier_for_key`` — the skill mod
    (``skills[skill]``) takes precedence when a skill is named and present; else
    the ability mod (``ability_mods[ability]``); else +0. The sidecar shape is
    ``{entity_id: {"skills": {code: mod}, "ability_mods": {ability: mod}}}``.
    """
    actor_mods = ctx.check_modifiers.get(actor.entity_id, {})
    if skill is not None:
        skills = actor_mods.get("skills", {})
        if skill in skills:
            return skills[skill]
    ability_mods = actor_mods.get("ability_mods", {})
    return ability_mods.get(ability, 0)
