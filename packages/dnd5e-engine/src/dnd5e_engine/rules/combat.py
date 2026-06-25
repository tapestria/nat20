"""Combat resolution — attack rolls, damage, saving throws."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from dnd5e_engine.rules.conditions import Condition, is_condition_active
from dnd5e_engine.rules.dice import RollResult, ability_modifier, roll, roll_d20
from dnd5e_engine.types.intent import CombatOutcome

if TYPE_CHECKING:
    from dnd5e_engine.types.effects import ActiveEffect


class HitType(StrEnum):
    MISS = "MISS"
    HIT = "HIT"
    CRITICAL_HIT = "CRITICAL_HIT"


@dataclass(frozen=True)
class AttackResult:
    roll: RollResult
    hit_type: HitType
    target_ac: int
    attacker_bonus: int


@dataclass(frozen=True)
class DamageResult:
    dice_rolls: list[int]
    modifier: int
    total: int
    damage_type: str
    is_critical: bool


@dataclass(frozen=True)
class SavingThrowResult:
    roll: RollResult
    dc: int
    success: bool
    ability: str


def attack_roll(
    attacker_bonus: int,
    target_ac: int,
    advantage: bool = False,
    disadvantage: bool = False,
    attacker_conditions: list[str] | None = None,
    target_conditions: list[str] | None = None,
) -> AttackResult:
    """
    Resolve an attack roll.
    Advantage/disadvantage from conditions is applied on top of caller-specified flags.
    """
    from dnd5e_engine.rules.dice import roll_with_advantage, roll_with_disadvantage

    conditions = attacker_conditions or []
    t_conditions = target_conditions or []

    # Condition-based modifiers
    if is_condition_active(Condition.PRONE, t_conditions):
        # Melee attacks have advantage vs prone; ranged have disadvantage.
        # Caller must specify which type this is; we accept their flag as-is.
        pass
    if is_condition_active(Condition.BLINDED, conditions):
        disadvantage = True
    if is_condition_active(Condition.INVISIBLE, conditions):
        advantage = True
    if is_condition_active(Condition.PARALYZED, t_conditions):
        advantage = True
    if is_condition_active(Condition.RESTRAINED, conditions):
        disadvantage = True
    if is_condition_active(Condition.POISONED, conditions):
        disadvantage = True

    # Advantage and disadvantage cancel out
    if advantage and disadvantage:
        advantage = False
        disadvantage = False

    if advantage:
        d20_result = roll_with_advantage(modifier=attacker_bonus)
    elif disadvantage:
        d20_result = roll_with_disadvantage(modifier=attacker_bonus)
    else:
        d20_result = roll_d20(modifier=attacker_bonus)

    natural = d20_result.dice[0] if not (advantage or disadvantage) else max(d20_result.dice)

    if natural == 20:
        hit_type = HitType.CRITICAL_HIT
    elif natural == 1 or d20_result.total < target_ac:
        hit_type = HitType.MISS
    else:
        hit_type = HitType.HIT

    return AttackResult(
        roll=d20_result,
        hit_type=hit_type,
        target_ac=target_ac,
        attacker_bonus=attacker_bonus,
    )


def damage_roll(
    dice_count: int,
    dice_sides: int,
    modifier: int,
    damage_type: str,
    is_critical: bool = False,
) -> DamageResult:
    """
    Roll damage. On a critical hit, double the number of dice rolled (not modifier).
    """
    effective_count = dice_count * 2 if is_critical else dice_count
    result = roll(dice_sides, effective_count, modifier)
    return DamageResult(
        dice_rolls=result.dice,
        modifier=modifier,
        total=max(0, result.total),  # damage can't be negative
        damage_type=damage_type,
        is_critical=is_critical,
    )


def saving_throw(
    ability_score: int,
    is_proficient: bool,
    proficiency_bonus: int,
    dc: int,
    advantage: bool = False,
    disadvantage: bool = False,
    conditions: list[str] | None = None,
    ability: str = "",
    *,
    active_effects: Sequence[ActiveEffect],
) -> SavingThrowResult:
    """Resolve a saving throw against a DC.

    Args:
        ability: The ability type for this save (e.g. "strength", "dexterity").
                 Used to determine auto-fail vs disadvantage for PARALYZED/STUNNED.
    """
    from dnd5e_engine.rules.dice import roll_with_advantage, roll_with_disadvantage

    conds = conditions or []
    ability_lower = ability.lower()

    str_dex = ("strength", "dexterity")
    # PARALYZED: auto-fail STR and DEX saving throws (SRD)
    if is_condition_active(Condition.PARALYZED, conds) and ability_lower in str_dex:
        result = roll_d20(modifier=0)
        return SavingThrowResult(roll=result, dc=dc, success=False, ability=ability)
    # STUNNED: auto-fail STR and DEX saving throws (SRD, COND-02)
    if is_condition_active(Condition.STUNNED, conds) and ability_lower in str_dex:
        result = roll_d20(modifier=0)
        return SavingThrowResult(roll=result, dc=dc, success=False, ability=ability)
    # Non-STR/DEX saves for PARALYZED/STUNNED: apply disadvantage only
    paralyzed = is_condition_active(Condition.PARALYZED, conds)
    stunned = is_condition_active(Condition.STUNNED, conds)
    if paralyzed or stunned:
        disadvantage = True

    # Codex Phase 6 review iter-12 P2: also honor flag-based advantage /
    # disadvantage from active_effects (ieffect2 translator emits
    # restrained / blinded / etc. as flags.advantage.save.<ability> or
    # flags.disadvantage.save.<ability>). Mirrors the resolve_check
    # iter-10/11 fix. The broad form (no ability suffix) applies to
    # every save; the per-ability form only when matching this save's
    # ability.
    for eff in active_effects:
        for ch in eff.changes:
            if ch.mode != "override" or ch.value is not True:
                continue
            if ch.key == "flags.advantage.save":
                advantage = True
            elif ch.key == "flags.disadvantage.save":
                disadvantage = True
            elif (
                ch.key == f"flags.advantage.save.{ability_lower}"
                and ability_lower
            ):
                advantage = True
            elif (
                ch.key == f"flags.disadvantage.save.{ability_lower}"
                and ability_lower
            ):
                disadvantage = True

    modifier = ability_modifier(ability_score) + (proficiency_bonus if is_proficient else 0)

    if advantage and disadvantage:
        advantage = False
        disadvantage = False

    if advantage:
        result = roll_with_advantage(modifier=modifier)
    elif disadvantage:
        result = roll_with_disadvantage(modifier=modifier)
    else:
        result = roll_d20(modifier=modifier)

    # Apply active effect changes to saving throw (Phase 6 changes vocab)
    save_total = result.total
    if active_effects:
        from dnd5e_engine.rules.effects import apply_changes_to_check

        # Fold the generic save.bonus bucket AND the per-ability bucket
        # (save.<ability>.bonus). Mirrors resolve_check() which honors both
        # so a Cloak of Protection (save.bonus +1) and a Ring of Mind
        # Shielding (save.wisdom.bonus +N style) both land. Codex Phase 6
        # iter-6 P2.
        ability_lower = (ability or "").lower()
        for bucket_key in ("save.bonus", f"save.{ability_lower}.bonus" if ability_lower else ""):
            if not bucket_key:
                continue
            save_total, _ = apply_changes_to_check(
                base_total=save_total,
                bucket=bucket_key,
                effects=active_effects,
            )

    return SavingThrowResult(
        roll=result,
        dc=dc,
        success=save_total >= dc,
        ability=ability,
    )


def apply_damage(
    current_hp: int,
    max_hp: int,
    damage: int,
    resistances: list[str] | None = None,
    immunities: list[str] | None = None,
    damage_type: str = "",
) -> tuple[int, bool]:
    """
    Apply damage to a creature.
    Returns (new_hp, is_dead).
    Handles resistance (half damage) and immunity (no damage).
    """
    resistances = resistances or []
    immunities = immunities or []

    if damage_type in immunities:
        damage = 0
    elif damage_type in resistances:
        damage = damage // 2

    new_hp = max(0, current_hp - damage)
    is_dead = new_hp == 0
    return new_hp, is_dead


def apply_healing(current_hp: int, max_hp: int, healing: int) -> int:
    """Apply healing, capped at max HP."""
    return min(max_hp, current_hp + healing)


def death_saving_throw() -> tuple[bool, bool]:
    """
    Roll a death saving throw.
    Returns (success, critical_result).
    - Roll 10+ = success
    - Roll 20 = regain 1 HP (critical success), return (True, True)
    - Roll 1 = two failures (critical failure), return (False, True)
    """
    result = roll_d20()
    natural = result.dice[0]
    if natural == 20:
        return True, True
    elif natural == 1:
        return False, True
    return result.raw >= 10, False


def initiative_roll(dexterity_score: int) -> RollResult:
    """Roll initiative: d20 + DEX modifier."""
    return roll_d20(modifier=ability_modifier(dexterity_score))


def opportunity_attack_eligible(
    movement: bool,
    left_threatened_zone: bool,
    attacker_can_see: bool = True,
) -> bool:
    """Check if an opportunity attack can be made."""
    return movement and left_threatened_zone and attacker_can_see


# ---------------------------------------------------------------------------
# Player attack resolution (Phase 55)
# ---------------------------------------------------------------------------


def resolve_player_attack(
    action_type: str,  # "attack" | "cast_spell"
    attack_bonus: int,  # weapon or spell attack bonus (pre-computed by caller)
    target_ac: int,
    damage_dice: str,  # "2d6+3" -- already cantrip-scaled if applicable
    damage_type: str,
    damage_modifier: int,  # ability mod for weapon, 0 for spells
    target_name: str,
    target_hp_current: int,
    target_hp_max: int,
    target_resistances: list[str] | None = None,
    target_immunities: list[str] | None = None,
    is_auto_hit: bool = False,
    save_type: str | None = None,
    save_dc: int = 0,
    target_save_score: int = 10,
    half_on_save: bool = False,
    attacker_conditions: list[str] | None = None,
    target_conditions: list[str] | None = None,
    *,
    active_effects: Sequence[ActiveEffect],
    target_active_effects: Sequence[ActiveEffect],
) -> CombatOutcome:
    """Resolve a player attack against a target -- pure function, no I/O.

    Dispatches to one of four paths:
    1. Auto-hit spell: skip attack roll, roll damage, apply directly.
    2. Save-based spell: roll monster saving throw, apply full/half/zero damage.
    3. Standard attack/spell attack roll: d20 + bonus vs AC.

    Returns CombatOutcome with both totals (for Phase 2 LLM narration) and raw
    dice data (for DiceOutcome broadcast construction).
    """
    from dnd5e_engine.rules.gambits import parse_damage_dice

    dice_count, dice_sides, dice_mod = parse_damage_dice(damage_dice)

    # ── Consolidated modifier pipeline (Root Cause D fix) ─────────────────
    # Every modifier_type on every ActiveEffect has exactly one application
    # site, and every site lives here so no caller can forget one. Attacker
    # effects modify attacker-owned quantities (attack roll, damage output);
    # target effects modify target-owned quantities (AC, save roll).
    #
    #   modifier_type   source effects         applied to
    #   -------------   --------------------   ----------------------------
    #   attack_roll     active_effects         attack_total (path 3 only)
    #   damage          active_effects         dmg_total    (all 3 paths)
    #   saving_throw    target_active_effects  save_total   (path 2 only,
    #                                                        via saving_throw)
    #   ac              target_active_effects  effective_target_ac
    #                                          (path 3 only — save-based and
    #                                           auto-hit bypass AC entirely)
    from dnd5e_engine.rules.effects import apply_changes_to_check

    def _apply_damage_modifiers(base_damage: int) -> int:
        """Apply attacker's 'damage' bucket changes to a rolled damage total."""
        if not active_effects:
            return base_damage
        modified, _ = apply_changes_to_check(
            base_total=base_damage, bucket="damage.bonus", effects=active_effects
        )
        # Damage cannot be negative (e.g. a -1d4 damage modifier on a 3-damage
        # swing does not heal the target; it clamps at 0).
        return max(0, modified)

    # Path 1: Auto-hit spell (e.g., Magic Missile)
    if is_auto_hit:
        dmg = damage_roll(dice_count, dice_sides, damage_modifier + dice_mod, damage_type)
        modified_dmg_total = _apply_damage_modifiers(dmg.total)
        new_hp, is_dead = apply_damage(
            target_hp_current,
            target_hp_max,
            modified_dmg_total,
            target_resistances,
            target_immunities,
            damage_type,
        )
        actual_damage = target_hp_current - new_hp

        return CombatOutcome(
            hit=True,
            damage_dealt=actual_damage,
            damage_type=damage_type,
            attack_roll=0,
            target_ac=target_ac,
            is_critical=False,
            target_name=target_name,
            target_hp_remaining=new_hp,
            target_hp_max=target_hp_max,
            target_died=is_dead,
            raw_damage_dice=dmg.dice_rolls,
            raw_damage_modifier=dmg.modifier,
        )

    # Path 2: Save-based spell (e.g., Fireball -- DEX save)
    if save_type is not None:
        save = saving_throw(
            ability_score=target_save_score,
            is_proficient=False,
            proficiency_bonus=0,
            dc=save_dc,
            conditions=target_conditions,
            ability=save_type or "",
            # Target's own effects modify their saving throw — e.g. Bless on the
            # defender grants +1d4 to this save. Passing attacker-side active_effects
            # here would be wrong (that's why this is a separate parameter).
            active_effects=target_active_effects,
        )
        dmg = damage_roll(dice_count, dice_sides, damage_modifier + dice_mod, damage_type)
        modified_dmg_total = _apply_damage_modifiers(dmg.total)

        effective_damage = (
            (modified_dmg_total // 2 if half_on_save else 0) if save.success else modified_dmg_total
        )

        new_hp, is_dead = apply_damage(
            target_hp_current,
            target_hp_max,
            effective_damage,
            target_resistances,
            target_immunities,
            damage_type,
        )
        actual_damage = target_hp_current - new_hp

        return CombatOutcome(
            hit=True,  # Save-based spells always "hit" (target), save determines damage
            damage_dealt=actual_damage,
            damage_type=damage_type,
            attack_roll=0,
            target_ac=target_ac,
            is_critical=False,
            target_name=target_name,
            target_hp_remaining=new_hp,
            target_hp_max=target_hp_max,
            target_died=is_dead,
            raw_damage_dice=dmg.dice_rolls,
            raw_damage_modifier=dmg.modifier,
            raw_save_roll_total=save.roll.total,
            raw_save_dc=save.dc,
            raw_save_success=save.success,
        )

    # Codex Phase 6 review iter-12 P2: derive advantage / disadvantage
    # from flag-based active_effect changes so Faerie Fire on the target,
    # Invisible on the attacker, and ieffect2-translated PassiveEffects
    # like attack_advantage=-1 actually shift the d20 mechanic. Mirrors
    # the resolve_check iter-10 fix. Attacker flags come from
    # active_effects (the attacker's effects); target flags come from
    # target_active_effects (Faerie Fire grants attack ADVANTAGE to
    # attackers, so we flip the target's flag to attacker-side advantage).
    attack_adv = False
    attack_disadv = False
    for eff in active_effects:
        for ch in eff.changes:
            if ch.mode != "override" or ch.value is not True:
                continue
            if ch.key == "flags.advantage.attack":
                attack_adv = True
            elif ch.key == "flags.disadvantage.attack":
                attack_disadv = True
    for eff in target_active_effects:
        for ch in eff.changes:
            if ch.mode != "override" or ch.value is not True:
                continue
            # Faerie Fire on the target grants attackers advantage
            # against the target. ieffect2 translator encodes this as
            # flags.advantage.attack on the target (since the IR's
            # attack_advantage=+1 carries no actor/target distinction);
            # we lift it here.
            if ch.key == "flags.advantage.attack":
                attack_adv = True
            elif ch.key == "flags.disadvantage.attack":
                attack_disadv = True

    # Path 3: Standard attack roll (weapon or spell attack roll)
    atk = attack_roll(
        attack_bonus,
        target_ac,
        advantage=attack_adv,
        disadvantage=attack_disadv,
        attacker_conditions=attacker_conditions,
        target_conditions=target_conditions,
    )

    # Apply active effect changes to attack roll (Phase 6 changes vocab)
    attack_total = atk.roll.total
    if active_effects:
        attack_total, _effect_breakdown = apply_changes_to_check(
            base_total=attack_total, bucket="attack.roll.bonus", effects=active_effects
        )

    # Apply target-side 'ac' changes (Root Cause D fix): Ring of Protection,
    # Shield of Faith, etc. boost the target's defensive AC before the hit
    # comparison. Modifier source is target_active_effects (whatever the
    # TARGET is wearing / under), not active_effects (the ATTACKER's gear).
    effective_target_ac = target_ac
    if target_active_effects:
        effective_target_ac, _ac_breakdown = apply_changes_to_check(
            base_total=target_ac, bucket="ac.bonus", effects=target_active_effects
        )

    # Re-evaluate hit after effect modifiers applied
    natural = atk.roll.dice[0] if len(atk.roll.dice) == 1 else max(atk.roll.dice)
    if natural == 20:
        effective_hit_type = HitType.CRITICAL_HIT
    elif natural == 1 or attack_total < effective_target_ac:
        effective_hit_type = HitType.MISS
    else:
        effective_hit_type = HitType.HIT

    is_hit = effective_hit_type in (HitType.HIT, HitType.CRITICAL_HIT)
    is_crit = effective_hit_type == HitType.CRITICAL_HIT

    if is_hit:
        dmg = damage_roll(
            dice_count, dice_sides, damage_modifier + dice_mod, damage_type, is_critical=is_crit
        )
        modified_dmg_total = _apply_damage_modifiers(dmg.total)
        new_hp, is_dead = apply_damage(
            target_hp_current,
            target_hp_max,
            modified_dmg_total,
            target_resistances,
            target_immunities,
            damage_type,
        )
        actual_damage = target_hp_current - new_hp

        return CombatOutcome(
            hit=True,
            damage_dealt=actual_damage,
            damage_type=damage_type,
            attack_roll=attack_total,
            target_ac=effective_target_ac,
            is_critical=is_crit,
            target_name=target_name,
            target_hp_remaining=new_hp,
            target_hp_max=target_hp_max,
            target_died=is_dead,
            raw_attack_roll_dice=atk.roll.dice,
            raw_attack_roll_modifier=atk.attacker_bonus,
            raw_damage_dice=dmg.dice_rolls,
            raw_damage_modifier=dmg.modifier,
        )

    # Miss
    return CombatOutcome(
        hit=False,
        damage_dealt=0,
        damage_type=damage_type,
        attack_roll=attack_total,
        target_ac=effective_target_ac,
        is_critical=False,
        target_name=target_name,
        target_hp_remaining=target_hp_current,
        target_hp_max=target_hp_max,
        target_died=False,
        raw_attack_roll_dice=atk.roll.dice,
        raw_attack_roll_modifier=atk.attacker_bonus,
    )


__all__ = [
    "AttackResult",
    "DamageResult",
    "HitType",
    "SavingThrowResult",
    "apply_damage",
    "apply_healing",
    "attack_roll",
    "damage_roll",
    "death_saving_throw",
    "initiative_roll",
    "opportunity_attack_eligible",
    "resolve_player_attack",
    "saving_throw",
]
