"""Skill checks and ability checks."""

from __future__ import annotations

from dataclasses import dataclass

from dnd5e_engine.rules.dice import (
    RollResult,
    ability_modifier,
    roll_d20,
    roll_with_advantage,
    roll_with_disadvantage,
)

# D&D 5e skill → ability mapping
SKILL_ABILITIES: dict[str, str] = {
    "acrobatics": "dexterity",
    "animal_handling": "wisdom",
    "arcana": "intelligence",
    "athletics": "strength",
    "deception": "charisma",
    "history": "intelligence",
    "insight": "wisdom",
    "intimidation": "charisma",
    "investigation": "intelligence",
    "medicine": "wisdom",
    "nature": "intelligence",
    "perception": "wisdom",
    "performance": "charisma",
    "persuasion": "charisma",
    "religion": "intelligence",
    "sleight_of_hand": "dexterity",
    "stealth": "dexterity",
    "survival": "wisdom",
}

# Display names
SKILL_DISPLAY_NAMES: dict[str, str] = {
    "acrobatics": "Acrobatics",
    "animal_handling": "Animal Handling",
    "arcana": "Arcana",
    "athletics": "Athletics",
    "deception": "Deception",
    "history": "History",
    "insight": "Insight",
    "intimidation": "Intimidation",
    "investigation": "Investigation",
    "medicine": "Medicine",
    "nature": "Nature",
    "perception": "Perception",
    "performance": "Performance",
    "persuasion": "Persuasion",
    "religion": "Religion",
    "sleight_of_hand": "Sleight of Hand",
    "stealth": "Stealth",
    "survival": "Survival",
}


@dataclass(frozen=True)
class SkillCheckResult:
    roll: RollResult
    skill: str
    ability: str
    dc: int | None
    success: bool | None  # None if no DC given (e.g. contested roll)
    is_proficient: bool
    proficiency_bonus: int
    total_modifier: int


def skill_check(
    skill: str,
    ability_scores: dict[str, int],
    proficient_skills: list[str],
    proficiency_bonus: int,
    dc: int | None = None,
    advantage: bool = False,
    disadvantage: bool = False,
    expertise: bool = False,  # double proficiency
    jack_of_all_trades: bool = False,  # half proficiency even if not proficient
) -> SkillCheckResult:
    """
    Resolve a skill check.
    Returns result with total and optional success/fail vs DC.
    """
    normalized = skill.lower().replace(" ", "_")
    ability = SKILL_ABILITIES.get(normalized, "intelligence")
    score = ability_scores.get(ability, 10)

    is_proficient = normalized in [s.lower().replace(" ", "_") for s in proficient_skills]

    if expertise and is_proficient:
        prof_contribution = proficiency_bonus * 2
    elif is_proficient:
        prof_contribution = proficiency_bonus
    elif jack_of_all_trades:
        prof_contribution = proficiency_bonus // 2
    else:
        prof_contribution = 0

    modifier = ability_modifier(score) + prof_contribution

    if advantage and disadvantage:
        advantage = False
        disadvantage = False

    if advantage:
        result = roll_with_advantage(modifier=modifier)
    elif disadvantage:
        result = roll_with_disadvantage(modifier=modifier)
    else:
        result = roll_d20(modifier=modifier)

    success = (result.total >= dc) if dc is not None else None

    return SkillCheckResult(
        roll=result,
        skill=normalized,
        ability=ability,
        dc=dc,
        success=success,
        is_proficient=is_proficient,
        proficiency_bonus=proficiency_bonus,
        total_modifier=modifier,
    )


def passive_perception(wisdom_score: int, proficient: bool, proficiency_bonus: int) -> int:
    """10 + WIS modifier + proficiency if applicable."""
    modifier = ability_modifier(wisdom_score) + (proficiency_bonus if proficient else 0)
    return 10 + modifier


def ability_check(
    ability: str,
    ability_scores: dict[str, int],
    dc: int | None = None,
    advantage: bool = False,
    disadvantage: bool = False,
) -> SkillCheckResult:
    """Raw ability check (no skill proficiency)."""
    score = ability_scores.get(ability.lower(), 10)
    modifier = ability_modifier(score)

    if advantage and disadvantage:
        advantage = False
        disadvantage = False

    if advantage:
        result = roll_with_advantage(modifier=modifier)
    elif disadvantage:
        result = roll_with_disadvantage(modifier=modifier)
    else:
        result = roll_d20(modifier=modifier)

    success = (result.total >= dc) if dc is not None else None

    return SkillCheckResult(
        roll=result,
        skill="",
        ability=ability.lower(),
        dc=dc,
        success=success,
        is_proficient=False,
        proficiency_bonus=0,
        total_modifier=modifier,
    )


def saving_throw(
    ability: str,
    ability_scores: dict[str, int],
    proficient_saves: list[str],
    proficiency_bonus: int,
    dc: int | None = None,
    advantage: bool = False,
    disadvantage: bool = False,
) -> SkillCheckResult:
    """Resolve a saving throw against an optional DC.

    Mirrors `skill_check` shape: same `SkillCheckResult` return type so
    callers (and `resolve_check`) can treat all three roll kinds uniformly.
    `skill` is empty (saves have no skill name); `ability` is the saved
    ability; proficiency is determined by membership in `proficient_saves`.
    """
    ability_lower = ability.lower()
    score = ability_scores.get(ability_lower, 10)
    is_proficient = ability_lower in [s.lower() for s in proficient_saves]

    prof_contribution = proficiency_bonus if is_proficient else 0
    modifier = ability_modifier(score) + prof_contribution

    if advantage and disadvantage:
        advantage = False
        disadvantage = False

    if advantage:
        result = roll_with_advantage(modifier=modifier)
    elif disadvantage:
        result = roll_with_disadvantage(modifier=modifier)
    else:
        result = roll_d20(modifier=modifier)

    success = (result.total >= dc) if dc is not None else None

    return SkillCheckResult(
        roll=result,
        skill="",
        ability=ability_lower,
        dc=dc,
        success=success,
        is_proficient=is_proficient,
        proficiency_bonus=proficiency_bonus,
        total_modifier=modifier,
    )


def contested_check(
    roller_a_total: int,
    roller_b_total: int,
) -> int:
    """
    Compare two contested roll totals.
    Returns: 1 if A wins, -1 if B wins, 0 if A wins on tie
    (per 5e rules: ties favor active participant, i.e. A).
    """
    return 1 if roller_a_total >= roller_b_total else -1


__all__ = [
    "SKILL_ABILITIES",
    "SKILL_DISPLAY_NAMES",
    "SkillCheckResult",
    "ability_check",
    "contested_check",
    "passive_perception",
    "saving_throw",
    "skill_check",
]
