"""Equipment rules — AC calculation and armor proficiency checks.

Pure functions with zero DB imports. Used by the combat engine to calculate
AC from character equipment data fetched by build_dispatch_context().

Per D-05: deterministic rules engine handles all AC mechanics; LLM handles narrative only.
"""

from __future__ import annotations

from dnd5e_engine.rules.dice import ability_modifier

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_SLOTS: frozenset[str] = frozenset({"right_hand", "left_hand", "armor", "backpack"})

# Unarmed strike damage expression (used when no weapon is equipped)
UNARMED_STRIKE_DAMAGE = "1"

# ---------------------------------------------------------------------------
# AC calculation
# ---------------------------------------------------------------------------


def calculate_ac(
    armor_type: str,
    base_ac: int,
    max_dex_bonus: int | None,
    dex_score: int,
    has_shield: bool,
) -> int:
    """Calculate Armor Class per D&D 5e SRD rules.

    Args:
        armor_type: One of "unarmored", "light", "medium", "heavy".
        base_ac: Base AC of the armor (0 for unarmored).
        max_dex_bonus: Maximum dex modifier to add. None = no cap (light/unarmored).
            0 = no dex bonus (heavy). 2 = standard medium armor cap.
            -1 stored in Neo4j means no cap (convert to None before calling).
        dex_score: Character's dexterity ability score.
        has_shield: True if character has a shield equipped in off-hand.

    Returns:
        Integer AC value.
    """
    dex_mod = ability_modifier(dex_score)
    armor_lower = armor_type.lower()

    if armor_lower == "unarmored":
        ac = 10 + dex_mod
    elif armor_lower == "light":
        # Full dex bonus, no cap
        ac = base_ac + dex_mod
    elif armor_lower == "medium":
        # Dex bonus capped at max_dex_bonus (default 2)
        cap = max_dex_bonus if max_dex_bonus is not None else 2
        ac = base_ac + min(dex_mod, cap)
    elif armor_lower == "heavy":
        # Flat base_ac — dex entirely ignored
        ac = base_ac
    else:
        # Unknown armor type — fall back to unarmored calculation
        ac = 10 + dex_mod

    if has_shield:
        ac += 2

    return ac


# ---------------------------------------------------------------------------
# Armor proficiency check
# ---------------------------------------------------------------------------


def is_armor_proficient(armor_type: str, class_armor_proficiencies: list[str]) -> bool:
    """Check if a character is proficient with the given armor type.

    SRD proficiency strings are "light", "medium", "heavy", "shields" (plural).
    The shield armor_type is "shield" (singular). Both forms are handled.

    Args:
        armor_type: Armor type to check (e.g. "light", "medium", "heavy", "shield").
        class_armor_proficiencies: List of proficiency strings from the class
            (e.g. ["light", "medium", "shields"]).

    Returns:
        True if the character is proficient with this armor type.
    """
    lower_type = armor_type.lower()
    lower_profs = [p.lower() for p in class_armor_proficiencies]

    # Direct match
    if lower_type in lower_profs:
        return True

    # Handle shield (singular) vs shields (plural) in proficiency list
    return lower_type == "shield" and "shields" in lower_profs


__all__ = [
    "UNARMED_STRIKE_DAMAGE",
    "VALID_SLOTS",
    "calculate_ac",
    "is_armor_proficient",
]
