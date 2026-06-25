"""Spell slot management and spell resolution helpers."""

from __future__ import annotations

from dataclasses import dataclass, field

# ── Spell slot tables (PHB) ───────────────────────────────────────────────────
# SPELL_SLOTS[class_level - 1][slot_level - 1] = count
FULL_CASTER_SLOTS: list[list[int]] = [
    [2, 0, 0, 0, 0, 0, 0, 0, 0],  # Level 1
    [3, 0, 0, 0, 0, 0, 0, 0, 0],  # Level 2
    [4, 2, 0, 0, 0, 0, 0, 0, 0],  # Level 3
    [4, 3, 0, 0, 0, 0, 0, 0, 0],  # Level 4
    [4, 3, 2, 0, 0, 0, 0, 0, 0],  # Level 5
    [4, 3, 3, 0, 0, 0, 0, 0, 0],  # Level 6
    [4, 3, 3, 1, 0, 0, 0, 0, 0],  # Level 7
    [4, 3, 3, 2, 0, 0, 0, 0, 0],  # Level 8
    [4, 3, 3, 3, 1, 0, 0, 0, 0],  # Level 9
    [4, 3, 3, 3, 2, 0, 0, 0, 0],  # Level 10
    [4, 3, 3, 3, 2, 1, 0, 0, 0],  # Level 11
    [4, 3, 3, 3, 2, 1, 0, 0, 0],  # Level 12
    [4, 3, 3, 3, 2, 1, 1, 0, 0],  # Level 13
    [4, 3, 3, 3, 2, 1, 1, 0, 0],  # Level 14
    [4, 3, 3, 3, 2, 1, 1, 1, 0],  # Level 15
    [4, 3, 3, 3, 2, 1, 1, 1, 0],  # Level 16
    [4, 3, 3, 3, 2, 1, 1, 1, 1],  # Level 17
    [4, 3, 3, 3, 3, 1, 1, 1, 1],  # Level 18
    [4, 3, 3, 3, 3, 2, 1, 1, 1],  # Level 19
    [4, 3, 3, 3, 3, 2, 2, 1, 1],  # Level 20
]

# Half-casters (Paladin, Ranger) round down
HALF_CASTER_SLOTS: list[list[int]] = [
    [0, 0, 0, 0, 0, 0, 0, 0, 0],  # Level 1
    [2, 0, 0, 0, 0, 0, 0, 0, 0],  # Level 2
    [3, 0, 0, 0, 0, 0, 0, 0, 0],  # Level 3
    [3, 0, 0, 0, 0, 0, 0, 0, 0],  # Level 4
    [4, 2, 0, 0, 0, 0, 0, 0, 0],  # Level 5
    [4, 2, 0, 0, 0, 0, 0, 0, 0],  # Level 6
    [4, 3, 0, 0, 0, 0, 0, 0, 0],  # Level 7
    [4, 3, 0, 0, 0, 0, 0, 0, 0],  # Level 8
    [4, 3, 2, 0, 0, 0, 0, 0, 0],  # Level 9
    [4, 3, 2, 0, 0, 0, 0, 0, 0],  # Level 10
    [4, 3, 3, 0, 0, 0, 0, 0, 0],  # Level 11
    [4, 3, 3, 0, 0, 0, 0, 0, 0],  # Level 12
    [4, 3, 3, 1, 0, 0, 0, 0, 0],  # Level 13
    [4, 3, 3, 1, 0, 0, 0, 0, 0],  # Level 14
    [4, 3, 3, 2, 0, 0, 0, 0, 0],  # Level 15
    [4, 3, 3, 2, 0, 0, 0, 0, 0],  # Level 16
    [4, 3, 3, 3, 1, 0, 0, 0, 0],  # Level 17
    [4, 3, 3, 3, 1, 0, 0, 0, 0],  # Level 18
    [4, 3, 3, 3, 2, 0, 0, 0, 0],  # Level 19
    [4, 3, 3, 3, 2, 0, 0, 0, 0],  # Level 20
]

FULL_CASTER_CLASSES = {"wizard", "bard"}
HALF_CASTER_CLASSES = {"paladin", "ranger"}
THIRD_CASTER_CLASSES = {"arcane_trickster", "eldritch_knight"}


@dataclass
class SpellSlotState:
    """Mutable spell slot tracker for a character."""

    total: list[int] = field(default_factory=lambda: [0] * 9)
    used: list[int] = field(default_factory=lambda: [0] * 9)

    @property
    def remaining(self) -> list[int]:
        return [t - u for t, u in zip(self.total, self.used, strict=True)]


def spell_slots_for_class(class_name: str, level: int) -> list[int]:
    """Return the spell slot counts for a class at a given level."""
    if level < 1 or level > 20:
        raise ValueError(f"Invalid level: {level}")
    cls = class_name.lower()
    if cls in FULL_CASTER_CLASSES:
        return FULL_CASTER_SLOTS[level - 1][:]
    elif cls in HALF_CASTER_CLASSES:
        return HALF_CASTER_SLOTS[level - 1][:]
    else:
        return [0] * 9


def spell_slot_cost(spell_level: int) -> int:
    """A spell costs one slot of its level (or higher)."""
    if spell_level < 0 or spell_level > 9:
        raise ValueError(f"Invalid spell level: {spell_level}")
    return 1  # Always costs 1 slot of the appropriate level


def can_cast(slots: SpellSlotState, spell_level: int) -> bool:
    """Check if the character has an available slot of the required level."""
    if spell_level == 0:
        return True  # Cantrips are unlimited
    return slots.remaining[spell_level - 1] > 0


def expend_slot(slots: SpellSlotState, slot_level: int) -> SpellSlotState:
    """Expend one spell slot of the given level. Returns new state."""
    if slot_level == 0:
        return slots  # Cantrips don't use slots
    idx = slot_level - 1
    if slots.remaining[idx] <= 0:
        raise ValueError(f"No spell slots remaining at level {slot_level}")
    new_used = slots.used[:]
    new_used[idx] += 1
    return SpellSlotState(total=slots.total[:], used=new_used)


def concentration_check(
    constitution_score: int,
    proficient: bool,
    proficiency_bonus: int,
    damage_taken: int,
) -> bool:
    """
    DC = max(10, damage // 2).
    Returns True if concentration is maintained.
    """
    from dnd5e_engine.rules.dice import ability_modifier, roll_d20

    dc = max(10, damage_taken // 2)
    modifier = ability_modifier(constitution_score) + (proficiency_bonus if proficient else 0)
    result = roll_d20(modifier=modifier)
    return result.total >= dc


def upcast_bonus_dice(_base_dice: str, base_level: int, cast_level: int) -> int:
    """
    Return the number of additional dice when upcasting.
    E.g. Cure Wounds (1d8 per level above 1st).
    """
    return max(0, cast_level - base_level)


__all__ = [
    "FULL_CASTER_CLASSES",
    "FULL_CASTER_SLOTS",
    "HALF_CASTER_CLASSES",
    "HALF_CASTER_SLOTS",
    "THIRD_CASTER_CLASSES",
    "SpellSlotState",
    "can_cast",
    "concentration_check",
    "expend_slot",
    "spell_slot_cost",
    "spell_slots_for_class",
    "upcast_bonus_dice",
]
