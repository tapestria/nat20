"""Combat data helpers — spell scaling, modifiers, weapon stats.

Pure functions with zero DB imports. Used by the combat engine to calculate
derived stats from structured spell and weapon data.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from dnd5e_engine.rules._class_meta import CASTER_CLASS_SLUGS
from dnd5e_engine.rules.dice import ability_modifier
from dnd5e_engine.rules.gambits import parse_damage_dice

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SpellCombatData:
    """Structured combat fields for a spell."""

    slug: str
    name: str
    level: int  # 0 = cantrip

    damage_dice: str | None = None
    damage_type: str | None = None
    save_type: str | None = None
    auto_hit: bool = False
    is_attack_roll: bool = False
    half_on_save: bool = False
    scaling_dice: str | None = None
    scaling_levels: list[int] | None = field(default=None)
    upcast_dice: str | None = None
    effect_type: str | None = None
    condition_applied: str | None = None
    target_type: str | None = None


@dataclass(frozen=True)
class WeaponStats:
    """Structured weapon stats from a character's inventory item."""

    item_id: str
    name: str
    damage_dice: str
    damage_type: str
    weapon_range: str  # "Melee" or "Ranged"
    category_range: str  # "Simple Melee", "Martial Ranged", etc.

    versatile_dice: str | None = None
    is_finesse: bool = False
    is_light: bool = False
    is_thrown: bool = False
    is_heavy: bool = False
    is_two_handed: bool = False


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CLASS_SPELLCASTING_ABILITY: dict[str, str] = {
    # Full casters (SRD 5.1)
    "bard": "charisma",
    "cleric": "wisdom",
    "druid": "wisdom",
    "sorcerer": "charisma",
    "warlock": "charisma",
    "wizard": "intelligence",
    # Half casters with spell lists (SRD 5.1)
    "paladin": "charisma",
    "ranger": "wisdom",
}

assert set(CLASS_SPELLCASTING_ABILITY) == CASTER_CLASS_SLUGS, (
    "CLASS_SPELLCASTING_ABILITY keys must match the manifest's caster class set"
)

UNARMED_STRIKE_DAMAGE_TYPE = "bludgeoning"


# ---------------------------------------------------------------------------
# Cantrip scaling
# ---------------------------------------------------------------------------


def calculate_cantrip_dice(
    base_dice: str,
    scaling_dice: str | None,
    scaling_levels: list[int] | None,
    character_level: int,
) -> str:
    """Calculate cantrip damage dice at a given character level.

    Uses scaling_dice and scaling_levels to determine how many extra dice
    are added. Returns the total dice expression (e.g., "3d10").

    If scaling_dice or scaling_levels is None, returns base_dice unchanged.
    """
    if scaling_dice is None or scaling_levels is None:
        return base_dice

    base_count, base_sides, _base_mod = parse_damage_dice(base_dice)
    scaling_count, _scaling_sides, _scaling_mod = parse_damage_dice(scaling_dice)

    tiers_reached = sum(1 for lvl in scaling_levels if character_level >= lvl)
    total_count = base_count + (scaling_count * tiers_reached)

    return f"{total_count}d{base_sides}"


# ---------------------------------------------------------------------------
# Spell modifiers
# ---------------------------------------------------------------------------


def spell_attack_bonus(
    class_slug: str,
    ability_scores: dict[str, int],
    proficiency_bonus: int,
) -> int | None:
    """Calculate spell attack bonus for a caster class.

    Returns None for non-caster classes (not in CLASS_SPELLCASTING_ABILITY).
    Formula: ability_modifier(spellcasting_ability) + proficiency_bonus
    """
    casting_ability = CLASS_SPELLCASTING_ABILITY.get(class_slug.lower())
    if casting_ability is None:
        return None

    ability_score = ability_scores.get(casting_ability, 10)
    return ability_modifier(ability_score) + proficiency_bonus


def spell_save_dc(
    class_slug: str,
    ability_scores: dict[str, int],
    proficiency_bonus: int,
) -> int | None:
    """Calculate spell save DC for a caster class.

    Returns None for non-caster classes (not in CLASS_SPELLCASTING_ABILITY).
    Formula: 8 + proficiency_bonus + ability_modifier(spellcasting_ability)
    """
    casting_ability = CLASS_SPELLCASTING_ABILITY.get(class_slug.lower())
    if casting_ability is None:
        return None

    ability_score = ability_scores.get(casting_ability, 10)
    return 8 + proficiency_bonus + ability_modifier(ability_score)


# ---------------------------------------------------------------------------
# Unarmed strike
# ---------------------------------------------------------------------------


def unarmed_strike_damage(strength_score: int) -> int:
    """Calculate unarmed strike damage: max(1, 1 + STR modifier)."""
    return max(1, 1 + ability_modifier(strength_score))


# ---------------------------------------------------------------------------
# Weapon helpers
# ---------------------------------------------------------------------------


def weapon_attack_bonus(
    ability_scores: dict[str, int],
    proficiency_bonus: int,
    is_proficient: bool,
    weapon_range: str,
    is_finesse: bool,
) -> int:
    """Calculate weapon attack bonus.

    - Melee: uses STR modifier
    - Ranged: uses DEX modifier
    - Finesse (melee only): uses higher of STR/DEX modifier
    - Proficient: adds proficiency_bonus

    weapon_range: "Melee" or "Ranged" (from Item.weapon_range)
    """
    str_mod = ability_modifier(ability_scores.get("strength", 10))
    dex_mod = ability_modifier(ability_scores.get("dexterity", 10))

    if weapon_range.lower() == "ranged":
        mod = dex_mod
    elif is_finesse:
        mod = max(str_mod, dex_mod)
    else:
        mod = str_mod

    if is_proficient:
        mod += proficiency_bonus

    return mod


def is_weapon_proficient(
    weapon_category_range: str,
    class_weapon_proficiencies: list[str],
) -> bool:
    """Check if a character is proficient with a weapon type.

    weapon_category_range: e.g., "Simple Melee", "Martial Ranged"
    class_weapon_proficiencies: e.g., ["simple"], ["martial", "simple"]

    Returns True if category_range starts with any proficiency (case-insensitive).
    """
    cat_lower = weapon_category_range.lower()
    return any(cat_lower.startswith(prof.lower()) for prof in class_weapon_proficiencies)


__all__ = [
    "CASTER_CLASS_SLUGS",
    "CLASS_SPELLCASTING_ABILITY",
    "UNARMED_STRIKE_DAMAGE_TYPE",
    "SpellCombatData",
    "WeaponStats",
    "calculate_cantrip_dice",
    "is_weapon_proficient",
    "spell_attack_bonus",
    "spell_save_dc",
    "unarmed_strike_damage",
    "weapon_attack_bonus",
]
