"""``attack`` kind handler for the Activity resolver.

A Foundry ``AttackActivity`` (``attack-data.mjs``) rolls a d20 attack vs the
target's AC; on a hit it rolls the weapon's base damage (when
``damage.include_base``) plus the activity's own ``damage.parts``, doubling the
dice and adding ``damage.critical.bonus`` on a crit. Canonical SRD 5.2 examples:
Fire Bolt (a ranged spell attack, single ``1d10`` fire activity part, no base
weapon), the Longsword (base ``1d8`` slashing, no activity parts), and the Mace
of Smiting (+1 weapon, base ``1d6`` bludgeoning, ``damage.critical.bonus == "7"``).

MIRRORS, does not import from, ``effects/attack.py`` + ``effects/damage.py``:

* The natural-d20 roll honors ``ctx.variables["force_d20"]`` (the test seam),
  else draws from ``ctx.rng`` — ``max`` of two for advantage, ``min`` of two for
  disadvantage, one otherwise (SRD §Advantage and Disadvantage). The mode is
  always ``"normal"`` today: the typed Outlined-effect layer does not yet encode
  an attack-advantage change, so no producer feeds a per-target adv/dis flag.
  Re-add a per-target reconciliation (consumer + producer together) when the
  data layer encodes Faerie-Fire-style ``flags.advantage.attack``.
* Hit / crit / miss mirrors ``effects/attack.py:_resolve_hit_outcome``: natural
  20 → auto crit+hit, natural 1 → auto miss, else ``total >= AC`` (SRD §Rolling
  1 or 20 / §Making an Attack). The crit threshold is ``attack.critical.threshold
  or 20``.
* Crit dice doubling + the modifier-once rule run through
  ``dice.roll_damage_part(crit=...)`` (SRD §Critical Hits). The activity-level
  ``damage.critical.bonus`` is a flat formula added ONCE on a crit, assigned to
  the first resolved damage type, mirroring ``effects/damage.py`` /
  ``activities/damage.py``.

Attack-bonus model (Foundry-structural / SRD-2024 ground truth):

* ``attack.flat`` True → the parsed ``attack.bonus`` formula ALONE — no ability
  mod, no proficiency, no weapon bonus (Foundry's flat-attack escape hatch).
* Otherwise → governing ability mod + proficiency (when ``ctx.is_proficient_attack``)
  + parsed ``attack.bonus`` formula + the weapon's ``magical_bonus`` (a +N weapon
  adds N to the attack roll). The governing ability is ``attack.ability`` when set;
  else the weapon's SRD default (melee non-finesse → STR, ranged → DEX, finesse →
  the better of STR/DEX) when a weapon is supplied; else the caster's spellcasting
  ability for a spell attack (Foundry stores ``""`` and resolves the default at
  runtime — see ``_governing_ability`` / ``_weapon_default_ability``).

Base weapon damage (``damage.include_base`` with a weapon supplied): each
``Weapon.damage_parts`` entry is rolled (crit-doubled on a crit) keyed by its
``damage_type``; the governing ability mod AND the weapon's ``magical_bonus`` are
added to the FIRST weapon damage part (Foundry folds ``@mod`` into the first
weapon damage term, and a +N weapon adds N to damage as well as to-hit — SRD
§Magic Weapons). The weapon ``DamagePart.dice`` is a bare ``"1d8"`` with no mod
baked in, so the mod is added here, not double-counted.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import TYPE_CHECKING

from dnd5e_srd_data.schema.item import WeaponProperty

from dnd5e_engine.activities.apply import apply_damage
from dnd5e_engine.activities.dice import roll_damage_part, roll_expr
from dnd5e_engine.activities.effects import apply_activity_effects
from dnd5e_engine.activities.formula import resolve_damage_block, resolve_roll_data
from dnd5e_engine.activities.mastery import apply_mastery_on_hit, apply_mastery_on_miss
from dnd5e_engine.events import AdvantageMode, AttackRolled

if TYPE_CHECKING:
    from dnd5e_srd_data.schema.common import AttackActivity, DamagePartBlock
    from dnd5e_srd_data.schema.item import Weapon

    from dnd5e_engine.types.combat import Combatant

    from .context import ActivityResolutionContext

_LOGGER = logging.getLogger(__name__)

# In-crit signal key consumed by the shared dice helper's crit path — the same
# convention ``activities/damage.py`` reads. Scoped to a single target+call here.
_IN_CRIT = "in_crit"


def resolve_attack(
    activity: AttackActivity,
    ctx: ActivityResolutionContext,
    *,
    weapon: Weapon | None = None,
) -> None:
    """Roll an attack vs each target and apply on-hit damage.

    For each target: compute the attack bonus once (it does not vary per target),
    roll the natural d20, derive hit/crit, emit ``AttackRolled``, and on a hit roll
    + apply the base weapon damage and the activity damage parts (crit-doubled, with
    the activity crit bonus on a crit), then fire the activity's effect riders
    (``EffectApplied`` then ``ConditionApplied``). Foundry applies attack riders on
    a HIT only — a miss applies no rider.
    """
    governing_ability = _governing_ability(activity, ctx, weapon)
    attack_bonus = _attack_bonus(activity, ctx, weapon, governing_ability)
    cast_level = ctx.slot_level or ctx.base_spell_level or 0
    # SRD §Bless / §Bane apply a signed d4 to the affected creature's OWN attack
    # rolls (keyed on the attacker). Rolled once per attack so each swing draws a
    # fresh d4 in the seeded stream — mirrors save_primitive's passive_save_bonus.
    attack_bonus_expr = ctx.passive_attack_bonus.get(ctx.caster.entity_id)

    for index, target in enumerate(ctx.targets):
        # No producer feeds per-target attack adv/dis today (the typed Outlined
        # effect layer does not yet encode an attack-advantage change), so the
        # mode is always normal. Re-add a per-target reconciliation when the data
        # layer encodes Faerie-Fire-style ``flags.advantage.attack``.
        mode: AdvantageMode = "normal"
        natural = _roll_natural_d20(ctx, mode, target_index=index)
        total = natural + attack_bonus
        if attack_bonus_expr:
            total += roll_expr(attack_bonus_expr, ctx.rng)
        is_crit, is_hit = _resolve_hit_outcome(natural, total, target.ac, activity)

        ctx.event_emitter(
            AttackRolled(
                attacker_id=ctx.caster.entity_id,
                target_id=target.entity_id,
                roll_total=total,
                advantage=mode,
                is_crit=is_crit,
                is_hit=is_hit,
                is_opportunity_attack=False,
            )
        )

        if is_hit:
            _apply_on_hit_damage(activity, ctx, target, weapon, governing_ability, is_crit=is_crit)
            apply_mastery_on_hit(weapon, ctx, target, governing_ability)
            apply_activity_effects(
                activity, ctx, target, save_succeeded=None, cast_level=cast_level
            )
        else:
            apply_mastery_on_miss(weapon, ctx, target, governing_ability)


# ── attack-bonus resolution ──────────────────────────────────────────────────


def _governing_ability(
    activity: AttackActivity, ctx: ActivityResolutionContext, weapon: Weapon | None
) -> str | None:
    """The ability that governs the attack roll and base weapon damage.

    Resolution order (Foundry stores ``""`` and resolves the default at runtime):

    1. ``attack.ability`` when set (non-empty) → use it verbatim.
    2. else if a ``weapon`` is supplied → the weapon's SRD default ability
       (``_weapon_default_ability``): a melee non-finesse weapon uses STR, a
       ranged weapon uses DEX, and a finesse weapon uses whichever of STR/DEX
       has the higher modifier.
    3. else (a spell attack with no weapon) → the caster's spellcasting ability.

    ``None`` only when neither a weapon nor a spellcasting ability is available
    (a flat attack needs no ability and simply contributes a +0 mod).
    """
    if activity.attack.ability:
        return activity.attack.ability
    if weapon is not None:
        return _weapon_default_ability(weapon, ctx)
    return ctx.spellcasting_ability


# Foundry ``weapon_category`` values that are ranged (DEX-governed by default).
_RANGED_CATEGORIES = frozenset({"simple_ranged", "martial_ranged"})


def _is_melee_weapon(weapon: Weapon | None) -> bool:
    """True iff ``weapon`` is a melee weapon (Foundry mwak scope).

    A melee weapon attack is the scope of ``system.bonuses.mwak.damage`` (Rage's
    Rage Damage). A spell attack (no weapon) and a ranged weapon are excluded.
    """
    return weapon is not None and weapon.weapon_category not in _RANGED_CATEGORIES


def _weapon_default_ability(weapon: Weapon, ctx: ActivityResolutionContext) -> str:
    """SRD default attack/damage ability for a weapon with no explicit ability.

    * ranged weapon (``weapon_category`` in the ranged set) → DEX.
    * finesse weapon (the ``finesse`` :class:`WeaponProperty`) → the better of the
      caster's STR/DEX modifier (SRD §Finesse: the wielder chooses).
    * otherwise (melee non-finesse) → STR.

    A weapon that is both ranged AND finesse (none in the SRD corpus, but the
    schema permits it) takes the finesse better-of branch, matching SRD intent
    that finesse always grants the STR/DEX choice.
    """
    if WeaponProperty.FINESSE in weapon.properties:
        return "str" if ctx.ability_mod("str") >= ctx.ability_mod("dex") else "dex"
    if weapon.weapon_category in _RANGED_CATEGORIES:
        return "dex"
    return "str"


def _attack_bonus(
    activity: AttackActivity,
    ctx: ActivityResolutionContext,
    weapon: Weapon | None,
    governing_ability: str | None,
) -> int:
    """Compute the to-hit modifier added to the natural d20.

    Flat attacks use the parsed ``attack.bonus`` formula alone. Otherwise the
    governing ability mod, proficiency (when proficient), the parsed
    ``attack.bonus`` formula, and the weapon's ``magical_bonus`` are summed.

    A cast wrapper's fixed challenge override (``ctx.attack_bonus_override``)
    bypasses all of that — a scroll/item to-hit (Circlet of Blasting +5) is used
    verbatim, since the item carries its own attack bonus, not the wielder's.
    """
    if ctx.attack_bonus_override is not None:
        return ctx.attack_bonus_override
    flat_formula = _resolve_flat_bonus(activity, ctx, governing_ability)
    if activity.attack.flat:
        return flat_formula

    bonus = flat_formula
    if governing_ability is not None:
        bonus += ctx.ability_mod(governing_ability)
    if ctx.is_proficient_attack:
        bonus += ctx.caster_proficiency_bonus
    if weapon is not None:
        bonus += weapon.magical_bonus
    return bonus


def _resolve_flat_bonus(
    activity: AttackActivity, ctx: ActivityResolutionContext, governing_ability: str | None
) -> int:
    """Resolve roll-data tokens in ``attack.bonus`` and fold it to an int.

    The bonus is a flat formula (canonical attacks ship it empty; magic weapons
    like the Mace of Smiting ship ``"2"``). It may carry ``@``-tokens, resolved
    against the governing ability before the seeded eval.
    """
    formula = activity.attack.bonus
    if not formula:
        return 0
    resolved = resolve_roll_data(formula, ctx, ability=governing_ability)
    return roll_expr(resolved, ctx.rng)


# ── natural d20 + hit/crit/miss ──────────────────────────────────────────────


def _roll_natural_d20(
    ctx: ActivityResolutionContext, mode: AdvantageMode, *, target_index: int = 0
) -> int:
    """Natural-d20 outcome, honoring ``variables["force_d20"]`` for determinism.

    The ``force_d20`` seam is a TEST hook scoped to the FIRST target only
    (``target_index == 0``); every other target rolls live off ``ctx.rng`` so a
    forced value never silently reuses one kept d20 across a multi-target attack.
    Mirrors ``effects/attack.py:_roll_natural_d20`` for the live path: advantage
    keeps the higher of two ``ctx.rng`` rolls, disadvantage the lower, normal one.
    """
    forced = ctx.variables.get("force_d20")
    if forced is not None and target_index == 0:
        return int(forced)
    if mode == "advantage":
        return max(ctx.rng.randint(1, 20), ctx.rng.randint(1, 20))
    if mode == "disadvantage":
        return min(ctx.rng.randint(1, 20), ctx.rng.randint(1, 20))
    return ctx.rng.randint(1, 20)


def _resolve_hit_outcome(
    natural: int, total: int, target_ac: int, activity: AttackActivity
) -> tuple[bool, bool]:
    """Derive ``(is_crit, is_hit)`` per SRD §Rolling 1 or 20 / §Making an Attack.

    Precedence: a natural 1 is ALWAYS an auto-miss (and never a crit), even when a
    degenerate ``critical.threshold`` of 1 would otherwise classify it as a crit —
    the SRD nat-1 rule wins. Then natural ≥ crit threshold
    (``attack.critical.threshold or 20``) → crit + hit; else ``total >= AC``.
    """
    if natural == 1:
        return False, False
    threshold = activity.attack.critical.threshold or 20
    if natural >= threshold:
        return True, True
    return False, total >= target_ac


# ── on-hit damage ────────────────────────────────────────────────────────────


def _apply_on_hit_damage(
    activity: AttackActivity,
    ctx: ActivityResolutionContext,
    target: Combatant,
    weapon: Weapon | None,
    governing_ability: str | None,
    *,
    is_crit: bool,
) -> None:
    """Roll base weapon damage + activity parts for one hit target and apply.

    Sets ``variables["in_crit"]`` for the duration of this target's damage rolls so
    the shared dice helper doubles dice on a crit, then restores the prior value so
    the signal never leaks to a sibling target or a later caller (mirrors
    ``effects/attack.py:_recurse_hit`` push/pop discipline).
    """
    previous = ctx.variables.get(_IN_CRIT)
    if is_crit:
        ctx.variables[_IN_CRIT] = 1
    try:
        by_type: dict[str, int] = defaultdict(int)
        first_type: str | None = None

        if activity.damage.include_base and weapon is not None:
            first_type = _roll_base_weapon_damage(
                weapon, ctx, by_type, governing_ability, is_crit=is_crit
            )

        for part in activity.damage.parts:
            damage_type = _part_type(part, activity.id, ctx)
            if damage_type is None:
                continue
            if first_type is None:
                first_type = damage_type
            resolved = resolve_damage_block(part, ctx, ability=governing_ability)
            by_type[damage_type] += roll_damage_part(
                resolved,
                ctx.rng,
                crit=is_crit,
                character_level=ctx.caster_level,
                slot_level=ctx.slot_level,
                base_level=ctx.base_spell_level,
            )

        if is_crit and activity.damage.critical.bonus and first_type is not None:
            by_type[first_type] += _resolve_critical_bonus(
                activity.damage.critical.bonus, ctx, governing_ability
            )

        # SRD §Rage / Foundry ``system.bonuses.mwak.damage`` — a melee weapon
        # attack damage bonus (Rage's +2 at L5) the caster carries as an active
        # effect, folded into the ``passive_melee_damage_bonus`` sidecar by the
        # orchestrator. Add it once to the first damage type, MELEE WEAPON only
        # (a weapon present that is not a ranged category) — never ranged or
        # spell. Rolled through ``ctx.rng`` so a dice-valued bonus lands in the
        # same seed stream (numeric bonuses are seed-inert).
        if first_type is not None and _is_melee_weapon(weapon):
            melee_bonus_expr = ctx.passive_melee_damage_bonus.get(ctx.caster.entity_id)
            if melee_bonus_expr:
                by_type[first_type] += roll_expr(melee_bonus_expr, ctx.rng)

        apply_damage(target, dict(by_type), ctx)
    finally:
        if is_crit:
            if previous is None:
                ctx.variables.pop(_IN_CRIT, None)
            else:
                ctx.variables[_IN_CRIT] = previous


def _roll_base_weapon_damage(
    weapon: Weapon,
    ctx: ActivityResolutionContext,
    by_type: dict[str, int],
    governing_ability: str | None,
    *,
    is_crit: bool,
) -> str | None:
    """Roll the weapon's base ``damage_parts`` into ``by_type``; return first type.

    Each part's bare ``.dice`` is rolled (crit-doubled). The governing ability mod
    and the weapon's ``magical_bonus`` are added once, to the FIRST part — Foundry
    folds ``@mod`` into the first weapon damage term, and a +N weapon adds N to
    damage (SRD §Magic Weapons). The weapon dice carry no mod, so adding here does
    not double-count.
    """
    first_type: str | None = None
    flat_addition = weapon.magical_bonus
    if governing_ability is not None:
        flat_addition += ctx.ability_mod(governing_ability)

    for index, part in enumerate(weapon.damage_parts):
        rolled = roll_damage_part(part, ctx.rng, crit=is_crit)
        if index == 0:
            rolled += flat_addition
            first_type = part.damage_type
        by_type[part.damage_type] += rolled
    return first_type


def _part_type(
    part: DamagePartBlock, activity_id: str, ctx: ActivityResolutionContext
) -> str | None:
    """The single damage type an activity part applies as.

    Mirrors ``activities/damage.py:_part_type``: a single-type part applies as that
    type; a multi-type part resolves the player's ``ctx.damage_type_choices`` (or
    defaults to the first, logged at INFO); a typeless part is logged and skipped.
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


def _resolve_critical_bonus(
    bonus: str, ctx: ActivityResolutionContext, governing_ability: str | None
) -> int:
    """Resolve @-tokens in ``damage.critical.bonus`` and fold it to an int.

    The crit bonus is a flat formula (the Mace of Smiting ships ``"7"``); it folds
    via the seeded rng for parity with the dice path even though the SRD corpus
    carries no dice in it.
    """
    resolved = resolve_roll_data(bonus, ctx, ability=governing_ability)
    return roll_expr(resolved, ctx.rng)
