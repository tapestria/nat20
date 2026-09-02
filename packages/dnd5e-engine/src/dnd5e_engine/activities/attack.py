"""``attack`` kind handler for the Activity resolver.

A Foundry ``AttackActivity`` (``attack-data.mjs``) rolls a d20 attack vs the
target's AC; on a hit it rolls the weapon's base damage (when
``damage.include_base``) plus the activity's own ``damage.parts``, doubling the
dice and adding ``damage.critical.bonus`` on a crit. Canonical SRD 5.2 examples:
Fire Bolt (a ranged spell attack, single ``1d10`` fire activity part, no base
weapon), the Longsword (base ``1d8`` slashing, no activity parts), and the Mace
of Smiting (+1 weapon, base ``1d6`` bludgeoning, ``damage.critical.bonus == "7"``).

MIRRORS, does not import from, ``effects/attack.py`` + ``effects/damage.py``:

* The natural-d20 roll goes through the single SRD 5.2 D20 Test primitive
  ``activities/d20.py::roll_d20_test``, honoring ``ctx.variables["force_d20"]``
  (the test seam, first target only) as ``forced_natural``. Advantage /
  disadvantage is LIVE (F2b): the mode is resolved from two typed source
  families — the attacker's own ``flags.advantage.attack`` /
  ``flags.disadvantage.attack`` effect changes (``attacker_advantage_flags`` →
  source ``"flag"``) and the condition-derived half
  (``rules/conditions.py::conditions_grant_advantage_on_attack``, called once
  per side over ``ctx.attacker_conditions`` / ``ctx.target_conditions[target]``
  so the emitted source names the side that produced it — ``"condition:attacker"``
  / ``"condition:target"``; both sides can produce either direction). Any advantage plus any
  disadvantage cancel to ``normal`` (SRD §Advantage and Disadvantage). A mode is
  only ever active when a source exists, so a scenario with no advantage
  producer still consumes exactly ONE d20 draw per target and its seeded stream
  is unchanged. The same flags additionally GATE the SRD §Sneak Attack trigger
  below. Prone (distance-aware via ``ctx.target_distance_ft``) and Grappled (via
  ``ctx.attacker_grappler_id``) are live since C12; unseen / long-range sources
  are C15/C16b.
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
from dnd5e_engine.activities.d20 import AdvantageSources, roll_d20_test
from dnd5e_engine.activities.dice import roll_damage_part, roll_expr
from dnd5e_engine.activities.effects import apply_activity_effects
from dnd5e_engine.activities.formula import resolve_damage_block, resolve_roll_data
from dnd5e_engine.activities.mastery import apply_mastery_on_hit, apply_mastery_on_miss
from dnd5e_engine.events import AdvantageMode, AdvantageSource, AttackRolled
from dnd5e_engine.rules.conditions import (
    conditions_auto_crit_within_5ft,
    conditions_grant_advantage_on_attack,
)
from dnd5e_engine.spatial import cover_bonus

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
    # SRD 5.2 Exhaustion — an attack roll is a D20 Test, so the flat
    # ``-2 x level`` penalty rides on the attack bonus (no extra draw).
    attack_bonus = _attack_bonus(
        activity, ctx, weapon, governing_ability
    ) + ctx.d20_test_penalty.get(ctx.caster.entity_id, 0)
    cast_level = ctx.slot_level or ctx.base_spell_level or 0
    # SRD §Bless / §Bane apply a signed d4 to the affected creature's OWN attack
    # rolls (keyed on the attacker). Rolled once per attack so each swing draws a
    # fresh d4 in the seeded stream — mirrors save_primitive's passive_save_bonus.
    attack_bonus_expr = ctx.passive_attack_bonus.get(ctx.caster.entity_id)
    # SRD §Making an Attack / §Magic Items — a magic weapon's bonus applies to
    # BOTH the attack roll and the damage roll made with it (the to-hit
    # analogue of ``passive_weapon_damage_bonus``, gated on a weapon being
    # present so it never leaks into a spell attack). Folded into the SAME
    # signed-dice-expr sum as the Bless/Bane bonus above so both draws land in
    # one roll_expr call, keeping the seeded stream shape unchanged when
    # neither sidecar is populated (the default/empty case).
    if weapon is not None:
        weapon_attack_bonus_expr = ctx.passive_weapon_attack_bonus.get(ctx.caster.entity_id)
        if weapon_attack_bonus_expr:
            attack_bonus_expr = (
                f"{attack_bonus_expr} + {weapon_attack_bonus_expr}"
                if attack_bonus_expr
                else weapon_attack_bonus_expr
            )

    # SRD §Advantage and Disadvantage — the attacker's own
    # ``flags.advantage.attack`` / ``flags.disadvantage.attack`` override
    # changes (both present cancel to normal, the legacy evaluator
    # ``reconcile_adv``). These both feed the d20 mode below (F2b) and gate the
    # SRD §Sneak Attack trigger.
    attacker_has_advantage, attacker_has_disadvantage = attacker_advantage_flags(ctx)
    # SRD 5.2 Heavy — ability-score-invariant per attack (see docstring);
    # computed once, outside the per-target loop, like the flag half above.
    heavy_disadvantage = _weapon_heavy_disadvantage(weapon, ctx.caster)

    for index, target in enumerate(ctx.targets):
        # Condition-derived half. The helper is called once PER SIDE (the other
        # side's list empty) purely so the emitted source can name which side
        # produced it: neither direction is one-way any more — an Invisible
        # attacker grants itself advantage while an Invisible TARGET imposes
        # disadvantage, and a Restrained attacker takes disadvantage while a
        # Restrained TARGET grants advantage. Every row in the helper reads
        # exactly one of its two arguments, so the split is exact.
        distance_ft = ctx.target_distance_ft.get(target.entity_id)
        attacker_cond_adv, attacker_cond_dis = conditions_grant_advantage_on_attack(
            ctx.attacker_conditions,
            [],
            grappler_id=ctx.attacker_grappler_id,
            target_id=target.entity_id,
        )
        target_cond_adv, target_cond_dis = conditions_grant_advantage_on_attack(
            [],
            ctx.target_conditions.get(target.entity_id, []),
            distance_ft=distance_ft,
        )
        adv_sources: list[AdvantageSource] = []
        dis_sources: list[AdvantageSource] = []
        if attacker_has_advantage:
            adv_sources.append("flag")
        if attacker_cond_adv:
            adv_sources.append("condition:attacker")
        if target_cond_adv:
            adv_sources.append("condition:target")
        if attacker_has_disadvantage:
            dis_sources.append("flag")
        if attacker_cond_dis:
            dis_sources.append("condition:attacker")
        if target_cond_dis:
            dis_sources.append("condition:target")
        # C16b — SRD 5.2 "Unseen Attackers and Targets": "When you make an
        # attack roll against a target you can't see, you have Disadvantage";
        # "When a creature can't see you, you have Advantage on attack rolls
        # against it." Both present cancel to normal in ``resolve_mode``.
        if ctx.attacker_unseen_by.get(target.entity_id):
            adv_sources.append("unseen")
        if ctx.target_unseen.get(target.entity_id):
            dis_sources.append("unseen")
        # SRD 5.2 §Actions in Combat — Dodge: "any attack roll made against
        # you has Disadvantage if you can see the attacker". The "can see
        # the attacker" conjunct is deferred to C16b (no vision model wired
        # to this seam yet); ``target_dodging`` already folds in the SRD
        # loss clause (Incapacitated / Speed 0) via
        # ``_dodge_benefit_active``.
        if ctx.target_dodging.get(target.entity_id):
            dis_sources.append("dodge")
        # SRD 5.2 §Range — "Your attack roll has Disadvantage when your
        # target is beyond normal range" (a target beyond a weapon's LONG
        # range is illegal and never reaches this resolver at all — gated
        # upstream, ``_pc_attack_out_of_range``). Pre-resolved per-target by
        # the orchestrator (``_target_beyond_normal_range_map``).
        if ctx.target_beyond_normal_range.get(target.entity_id):
            dis_sources.append("range:long")
        # SRD 5.2 "Ranged Attacks in Close Combat" (C15 Task 3): "you have
        # Disadvantage on the roll if you are within 5 feet of an enemy who
        # can see you and doesn't have the Incapacitated condition." The
        # spatial/incapacitated/vision predicate is pre-resolved orchestrator
        # -side (``_hostile_adjacent_to_attacker``) into the per-ATTACKER
        # ``ctx.attacker_ranged_in_melee`` flag; this pure resolver only
        # gates it on the attack itself being effectively ranged (a melee
        # swing, even with a hostile adjacent, is never penalized).
        if ctx.attacker_ranged_in_melee and _attack_is_effectively_ranged(weapon, distance_ft):
            dis_sources.append("ranged_in_melee")
        # SRD 5.2 Heavy — no dedicated ``AdvantageSource`` exists (controller
        # ruling, C15 task-3 brief): reuses ``"trait"``. Ability-invariant
        # per attack, computed once above.
        if heavy_disadvantage:
            dis_sources.append("trait")
        # SRD 5.2 §Actions in Combat — Help, Assist an Attack Roll: "giving
        # Advantage to the next attack roll by one of your allies against
        # that enemy". ``target_help_advantage`` is already gated to an
        # ally-of-this-attacker grant (orchestrator-side); the one-use pop
        # happens after resolution regardless of hit/miss/cancellation — see
        # ``target_help_advantage`` docstring.
        if ctx.target_help_advantage.get(target.entity_id):
            adv_sources.append("help")
        # SRD 5.2 §Weapon Mastery — Vex (C15 Task 6): "you have Advantage on
        # your next attack roll against that creature". No dedicated
        # ``AdvantageSource`` exists for mastery riders (controller ruling,
        # same "trait" reuse as Heavy below) — the Literal is closed.
        # ``target_attacker_has_advantage`` (below) folds this into the SAME
        # boolean ``sneak_attack_triggers`` reads, so a vex-advantaged Rogue
        # swing can Sneak Attack.
        target_vex_advantage = bool(ctx.attacker_vex_advantage.get(target.entity_id))
        if target_vex_advantage:
            adv_sources.append("trait")
        # SRD 5.2 §Weapon Mastery — Sap (C15 Task 6): "that creature has
        # Disadvantage on its next attack roll". Per-ATTACKER (the acting
        # caster may itself be sapped); reuses the SAME "trait" token.
        if ctx.attacker_sapped:
            dis_sources.append("trait")
        sources = AdvantageSources(advantage=tuple(adv_sources), disadvantage=tuple(dis_sources))
        roll = roll_d20_test(ctx.rng, attack_bonus, sources, forced_natural=_forced_d20(ctx, index))
        mode: AdvantageMode = roll.mode
        natural, total = roll.kept, roll.total
        if attack_bonus_expr:
            total += roll_expr(attack_bonus_expr, ctx.rng)
        # SRD 5.2 §Cover — half (+2) / three-quarters (+5) cover raises the
        # target's EFFECTIVE AC for this attack only; total cover is filtered
        # upstream (the target is never reachable as a resolver target at all).
        # SRD Shield — "+5 bonus to AC, including against the triggering
        # attack" a pre-armed reaction can land an AC-bonus active
        # effect on the target between the trigger and this comparison; the
        # natural roll itself is never touched, only this comparison.
        effective_ac = (
            target.ac
            + cover_bonus(ctx.target_cover.get(target.entity_id, "none"))
            + ctx.passive_ac_bonus.get(target.entity_id, 0)
        )
        auto_crit = (
            distance_ft is not None
            and distance_ft <= 5
            and conditions_auto_crit_within_5ft(ctx.target_conditions.get(target.entity_id, []))
        )
        is_crit, is_hit = _resolve_hit_outcome(
            natural, total, effective_ac, activity, auto_crit_on_hit=auto_crit
        )

        ctx.event_emitter(
            AttackRolled(
                attacker_id=ctx.caster.entity_id,
                target_id=target.entity_id,
                roll_total=total,
                advantage=mode,
                is_crit=is_crit,
                is_hit=is_hit,
                is_opportunity_attack=False,
                natural=roll.kept,
                modifier=attack_bonus,
                sources=list(roll.sources),
            )
        )

        if is_hit:
            # C15 Task 6 — Vex synergy: a vex-advantaged swing feeds the SAME
            # boolean ``sneak_attack_triggers`` reads as
            # ``attacker_has_advantage`` (the flag-based override), so a
            # vex-advantaged Rogue attack can Sneak Attack even without the
            # flag itself set.
            damage_dealt = _apply_on_hit_damage(
                activity,
                ctx,
                target,
                weapon,
                governing_ability,
                is_crit=is_crit,
                attacker_has_advantage=attacker_has_advantage or target_vex_advantage,
                attacker_has_disadvantage=attacker_has_disadvantage,
            )
            apply_mastery_on_hit(weapon, ctx, target, governing_ability, damage_dealt=damage_dealt)
            apply_activity_effects(
                activity, ctx, target, save_succeeded=None, cast_level=cast_level
            )
        else:
            apply_mastery_on_miss(weapon, ctx, target, governing_ability)


# ── attacker advantage / Sneak Attack production ─────────────────────────────


def attacker_advantage_flags(ctx: ActivityResolutionContext) -> tuple[bool, bool]:
    """Read the attacker's ``flags.advantage/disadvantage.attack`` override changes.

    SRD §Advantage and Disadvantage. Mirrors the attacker-flag half of
    ``rules/combat.py``'s reconciliation: an ``override``-mode change with value
    ``True`` on an effect the CASTER carries flips the corresponding flag. Only
    the caster's own effects count here (target-side Faerie-Fire production is
    deferred — see the migration note); an absent/empty ``active_effects`` yields
    ``(False, False)`` (``normal``), byte-identical to the prior hardcode.
    """
    has_advantage = False
    has_disadvantage = False
    for eff in ctx.active_effects:
        if eff.target_id != ctx.caster.entity_id:
            continue
        for ch in eff.changes:
            if ch.mode != "override" or ch.value is not True:
                continue
            if ch.key == "flags.advantage.attack":
                has_advantage = True
            elif ch.key == "flags.disadvantage.attack":
                has_disadvantage = True
    # Both present cancel to normal (the legacy evaluator ``reconcile_adv``).
    if has_advantage and has_disadvantage:
        return False, False
    return has_advantage, has_disadvantage


def sneak_attack_dice(ctx: ActivityResolutionContext) -> str | None:
    """The caster's Sneak Attack extra-damage dice expression, if granted.

    SRD §Sneak Attack (Rogue): the feature's ``damage.parts[0]`` formula is
    ``@scale.<class>.sneak-attack`` (``"3d6"`` at Rogue level 5). The
    orchestrator pre-resolves that ``@scale`` token into ``ctx.scale_values``
    at the build-party seam (loader access there); this pure resolver reads the
    already-resolved dice STRING keyed ``"<class>.sneak-attack"``. Absent ⇒ the
    caster has no Sneak Attack (``None``, no rider).
    """
    for key, value in ctx.scale_values.items():
        if key.endswith(".sneak-attack") and isinstance(value, str) and value:
            return value
    return None


def sneak_attack_triggers(
    ctx: ActivityResolutionContext,
    weapon: Weapon | None,
    target: Combatant,
    *,
    attacker_has_advantage: bool,
    attacker_has_disadvantage: bool,
) -> bool:
    """SRD §Sneak Attack trigger: a Finesse-or-Ranged weapon hit made with
    Advantage, OR (the ally-adjacent alternative) an ally within 5 ft of the
    target who is not Incapacitated while the attacker is not at Disadvantage.

    The ally-adjacent spatial predicate is evaluated orchestrator-side (a new
    consumer of ``spatial.py``) and delivered as the per-target
    ``ctx.sneak_attack_ally_adjacent`` flag; this pure resolver only reads it.
    A spell attack (no weapon) never qualifies.
    """
    if weapon is None:
        return False
    is_finesse = WeaponProperty.FINESSE in weapon.properties
    is_ranged = weapon.weapon_category in _RANGED_CATEGORIES
    if not (is_finesse or is_ranged):
        return False
    if attacker_has_advantage:
        return True
    # Ally-adjacent alternative: an adjacent, non-Incapacitated ally (computed
    # orchestrator-side) while the attacker is not at Disadvantage.
    ally_adjacent = bool(ctx.sneak_attack_ally_adjacent.get(target.entity_id))
    return ally_adjacent and not attacker_has_disadvantage


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


def _is_ranged_weapon(weapon: Weapon | None) -> bool:
    """True iff ``weapon`` is a ranged weapon (Foundry rwak scope).

    The ranged analog of ``_is_melee_weapon`` — the scope of
    ``system.bonuses.rwak.damage`` .
    """
    return weapon is not None and weapon.weapon_category in _RANGED_CATEGORIES


def _attack_is_effectively_ranged(weapon: Weapon | None, distance_ft: int | None) -> bool:
    """SRD 5.2 "Ranged Attacks in Close Combat" — is THIS attack, against
    THIS target, a ranged attack?

    A ranged-category weapon (bow/crossbow) always qualifies. A melee
    weapon carrying the Thrown property becomes a ranged attack only once
    it's actually being THROWN — i.e. the target is beyond the weapon's
    melee reach (5 ft, or 10 ft with the Reach property) — mirroring the
    orchestrator's range-tier split (``_weapon_attack_range_ft``): within
    reach it's an ordinary melee swing (never penalized here), beyond reach
    it's a thrown ranged attack. An ordinary melee-only weapon (no Thrown)
    is never ranged, and a spell attack (no weapon) never triggers this
    weapon-keyed gate — see the migration note on the monster attack ctx
    site (``orchestrator.py``) for why.
    """
    if weapon is None:
        return False
    if weapon.weapon_category in _RANGED_CATEGORIES:
        return True
    if WeaponProperty.THROWN not in weapon.properties:
        return False
    reach = 10 if WeaponProperty.REACH in weapon.properties else 5
    return distance_ft is not None and distance_ft > reach


def _weapon_heavy_disadvantage(weapon: Weapon | None, caster: Combatant) -> bool:
    """SRD 5.2 Heavy: "You have Disadvantage on attack rolls with a Heavy
    weapon if it's a Melee weapon and your Strength score isn't at least 13
    or if it's a Ranged weapon and your Dexterity score isn't at least 13."

    Ability-score-invariant per attack (unlike ``_attack_is_effectively_
    ranged``, this does not vary per target): a melee weapon with Thrown
    stays STR-gated even when thrown at range (SRD §Thrown — same ability
    as a melee attack with that weapon). No dedicated ``AdvantageSource``
    exists for Heavy (controller ruling, C15 task-3 brief): the caller
    appends the existing ``"trait"`` source.
    """
    if weapon is None or WeaponProperty.HEAVY not in weapon.properties:
        return False
    governing_score = (
        caster.dexterity if weapon.weapon_category in _RANGED_CATEGORIES else caster.strength
    )
    return governing_score < 13


def _is_melee_spell_attack(activity: AttackActivity, weapon: Weapon | None) -> bool:
    """True iff this is a melee SPELL attack (Foundry msak scope: no weapon,
    ``attack.type.value == "melee"`` — e.g. Shocking Grasp)."""
    return weapon is None and activity.attack.type.value == "melee"


def _is_ranged_spell_attack(activity: AttackActivity, weapon: Weapon | None) -> bool:
    """True iff this is a ranged SPELL attack (Foundry rsak scope: no weapon,
    ``attack.type.value == "ranged"`` — e.g. Fire Bolt)."""
    return weapon is None and activity.attack.type.value == "ranged"


def _weapon_default_ability(weapon: Weapon, ctx: ActivityResolutionContext) -> str:
    """SRD default attack/damage ability for a weapon with no explicit ability.

    * ranged weapon (``weapon_category`` in the ranged set) → DEX.
    * finesse weapon (the ``finesse`` ``WeaponProperty``) → the better of the
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


def _forced_d20(ctx: ActivityResolutionContext, target_index: int) -> int | None:
    """The ``variables["force_d20"]`` determinism seam, or ``None``.

    A TEST hook scoped to the FIRST target only (``target_index == 0``); every
    other target rolls live off ``ctx.rng`` so a forced value never silently
    reuses one kept d20 across a multi-target attack.
    """
    forced = ctx.variables.get("force_d20")
    if forced is not None and target_index == 0:
        return int(forced)
    return None


def _resolve_hit_outcome(
    natural: int,
    total: int,
    target_ac: int,
    activity: AttackActivity,
    *,
    auto_crit_on_hit: bool = False,
) -> tuple[bool, bool]:
    """Derive ``(is_crit, is_hit)`` per SRD §Rolling 1 or 20 / §Making an Attack.

    Precedence: a natural 1 is ALWAYS an auto-miss (and never a crit), even when a
    degenerate ``critical.threshold`` of 1 would otherwise classify it as a crit —
    the SRD nat-1 rule wins. Then natural ≥ crit threshold
    (``attack.critical.threshold or 20``) → crit + hit; else ``total >= AC``, and
    a hit is upgraded to a crit when ``auto_crit_on_hit`` (SRD 5.2 Paralyzed /
    Unconscious: "Any attack roll that hits you is a Critical Hit if the attacker
    is within 5 feet of you").
    """
    if natural == 1:
        return False, False
    threshold = activity.attack.critical.threshold or 20
    if natural >= threshold:
        return True, True
    is_hit = total >= target_ac
    return (is_hit and auto_crit_on_hit), is_hit


# ── on-hit damage ────────────────────────────────────────────────────────────


def _apply_on_hit_damage(
    activity: AttackActivity,
    ctx: ActivityResolutionContext,
    target: Combatant,
    weapon: Weapon | None,
    governing_ability: str | None,
    *,
    is_crit: bool,
    attacker_has_advantage: bool = False,
    attacker_has_disadvantage: bool = False,
) -> int:
    """Roll base weapon damage + activity parts for one hit target and apply.

    Sets ``variables["in_crit"]`` for the duration of this target's damage rolls so
    the shared dice helper doubles dice on a crit, then restores the prior value so
    the signal never leaks to a sibling target or a later caller (mirrors
    ``effects/attack.py:_recurse_hit`` push/pop discipline).

    Returns the total (post-modifier) damage actually dealt to ``target``
    (``apply_damage``'s return) — C15 Task 6 (Vex) needs this to gate its
    on-hit proc on damage actually landing, not merely a hit.
    """
    previous = ctx.variables.get(_IN_CRIT)
    if is_crit:
        ctx.variables[_IN_CRIT] = 1
    total_dealt = 0
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

        # / Foundry ``system.bonuses.rwak.damage`` — a ranged weapon
        # attack damage bonus, the ranged analog of the melee-only bonus just
        # above. Add it once to the first damage type, RANGED WEAPON only.
        if first_type is not None and _is_ranged_weapon(weapon):
            ranged_bonus_expr = ctx.passive_ranged_damage_bonus.get(ctx.caster.entity_id)
            if ranged_bonus_expr:
                by_type[first_type] += roll_expr(ranged_bonus_expr, ctx.rng)

        # Foundry ``system.bonuses.msak.damage`` / ``system.bonuses.rsak.damage``
        # — melee / ranged SPELL-attack damage bonuses (e.g. Shocking Grasp /
        # Fire Bolt). No weapon is present for a spell attack; gate on the
        # activity's own melee/ranged classification instead.
        if first_type is not None and _is_melee_spell_attack(activity, weapon):
            melee_spell_bonus_expr = ctx.passive_melee_spell_damage_bonus.get(ctx.caster.entity_id)
            if melee_spell_bonus_expr:
                by_type[first_type] += roll_expr(melee_spell_bonus_expr, ctx.rng)
        if first_type is not None and _is_ranged_spell_attack(activity, weapon):
            ranged_spell_bonus_expr = ctx.passive_ranged_spell_damage_bonus.get(
                ctx.caster.entity_id
            )
            if ranged_spell_bonus_expr:
                by_type[first_type] += roll_expr(ranged_spell_bonus_expr, ctx.rng)

        # SRD §Making an Attack / §Magic Items — a magic weapon's bonus
        # applies to BOTH the attack roll and the damage roll made with it.
        # Folded into the ``passive_weapon_damage_bonus`` sidecar by the
        # orchestrator (action-type-tagged so it never leaks into spell
        # attacks). Applies to ANY weapon swing (melee or ranged), unlike the
        # Rage-only melee bonus above. Add it once to the first damage type,
        # rolled through ``ctx.rng`` so a dice-valued bonus lands in the same
        # seed stream.
        if first_type is not None and weapon is not None:
            weapon_bonus_expr = ctx.passive_weapon_damage_bonus.get(ctx.caster.entity_id)
            if weapon_bonus_expr:
                by_type[first_type] += roll_expr(weapon_bonus_expr, ctx.rng)

        # SRD §Sneak Attack (Rogue) — once per turn, on a qualifying hit (Finesse
        # or Ranged weapon, made with Advantage OR the ally-adjacent alternative,
        # rider unspent this turn), add the feature's extra dice. Folded into the
        # FIRST damage type ("the extra damage's type is the same as the
        # weapon's"). Rolled through ``ctx.rng`` (via ``roll_expr``, matching the
        # passive-bonus fold pattern) so the dice land in the same seed stream.
        # On a crit the rider dice DOUBLE — SRD 5.2 §Critical Hit ("Roll all of
        # the attack's damage dice twice and add them together",
        # 09_rules_glossary.md; the rider is part of the attack's damage dice) —
        # via the SAME ``_double_dice`` count-doubling idiom the base-weapon
        # crit path (``roll_damage_part(crit=...)``) uses.
        # The once-per-turn cap gates the FOLD itself (``sneak_attack_spent``);
        # recording "spent" is an orchestrator-side concern (a per-turn
        # ``Combatant`` flag cleared at ``TurnStarted``).
        if (
            first_type is not None
            and weapon is not None
            and not ctx.sneak_attack_spent.get(ctx.caster.entity_id)
            and sneak_attack_triggers(
                ctx,
                weapon,
                target,
                attacker_has_advantage=attacker_has_advantage,
                attacker_has_disadvantage=attacker_has_disadvantage,
            )
        ):
            sneak_dice = sneak_attack_dice(ctx)
            if sneak_dice:
                by_type[first_type] += roll_expr(sneak_dice, ctx.rng, crit=is_crit)

        # C15 — damage-source attribution (``DamageApplied.source_id``): base
        # weapon damage attributes to the weapon's slug; a synthesized
        # legacy-fixture swing (no weapon, see
        # ``orchestrator._synthesize_attack_from_legacy_fields``) attributes to
        # its synthesized activity id instead. A non-weapon, non-synthesized
        # attack (e.g. a spell attack) leaves it ``None`` this cluster — cast
        # attribution is a C17+ seam.
        if weapon is not None:
            source_id: str | None = weapon.slug
        elif activity.id.startswith("synth:"):
            source_id = activity.id
        else:
            source_id = None

        # spell-delivered attack rolls are magical too (spells are magical effects)
        total_dealt = apply_damage(
            target,
            dict(by_type),
            ctx,
            magical=(weapon is not None and weapon.magical) or ctx.base_spell_level is not None,
            source_id=source_id,
            is_crit=is_crit,
        )
    finally:
        if is_crit:
            if previous is None:
                ctx.variables.pop(_IN_CRIT, None)
            else:
                ctx.variables[_IN_CRIT] = previous
    return total_dealt


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

    SRD 5.2 Versatile property — "The weapon deals that damage when used with
    two hands to make a melee attack." When ``ctx.use_versatile_damage`` is set
    (the orchestrator has already confirmed a two-handed grip + VERSATILE +
    melee swing) AND the weapon carries ``versatile_damage``, that single part
    is rolled INSTEAD OF ``damage_parts`` — crit doubling and the ability-mod
    fold apply identically to either die.
    """
    first_type: str | None = None
    flat_addition = weapon.magical_bonus
    if governing_ability is not None:
        mod = ctx.ability_mod(governing_ability)
        # SRD 5.2 Light property: "you don't add your ability modifier to the
        # extra attack's damage unless that modifier is negative."
        if ctx.suppress_positive_ability_damage_mod and mod > 0:
            mod = 0
        flat_addition += mod

    parts = weapon.damage_parts
    if ctx.use_versatile_damage and weapon.versatile_damage is not None:
        parts = [weapon.versatile_damage]

    for index, part in enumerate(parts):
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
