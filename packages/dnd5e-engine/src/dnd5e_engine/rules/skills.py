"""Skill checks and ability checks."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Final, Literal

from dnd5e_engine.rules.dice import (
    RollResult,
    ability_modifier,
    roll_d20,
    roll_with_advantage,
    roll_with_disadvantage,
)

Skill = Literal[
    "acrobatics",
    "animal_handling",
    "arcana",
    "athletics",
    "deception",
    "history",
    "insight",
    "intimidation",
    "investigation",
    "medicine",
    "nature",
    "perception",
    "performance",
    "persuasion",
    "religion",
    "sleight_of_hand",
    "stealth",
    "survival",
]

# Foundry's 3-letter skill codes (corpus ``Background.skill_proficiencies``,
# Trait grants, ``check.associated``) → the engine's canonical long-form slug.
SKILL_CODE_TO_SLUG: Final[dict[str, Skill]] = {
    "acr": "acrobatics",
    "ani": "animal_handling",
    "arc": "arcana",
    "ath": "athletics",
    "dec": "deception",
    "his": "history",
    "ins": "insight",
    "itm": "intimidation",
    "inv": "investigation",
    "med": "medicine",
    "nat": "nature",
    "prc": "perception",
    "prf": "performance",
    "per": "persuasion",
    "rel": "religion",
    "slt": "sleight_of_hand",
    "ste": "stealth",
    "sur": "survival",
}

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
    *,
    rng: random.Random | None = None,
    reliable_talent: bool = False,
) -> SkillCheckResult:
    """
    Resolve a skill check.
    Returns result with total and optional success/fail vs DC.
    """
    normalized = skill.lower().replace(" ", "_")
    ability = SKILL_ABILITIES.get(normalized, "intelligence")
    score = ability_scores.get(ability, 10)

    is_proficient = normalized in [s.lower().replace(" ", "_") for s in proficient_skills]

    prof_contribution = skill_proficiency_bonus(
        proficiency_bonus,
        proficient=is_proficient,
        expertise=expertise,
        jack_of_all_trades=jack_of_all_trades,
    )

    modifier = ability_modifier(score) + prof_contribution

    if advantage and disadvantage:
        advantage = False
        disadvantage = False

    if advantage:
        result = roll_with_advantage(modifier=modifier, rng=rng)
    elif disadvantage:
        result = roll_with_disadvantage(modifier=modifier, rng=rng)
    else:
        result = roll_d20(modifier=modifier, rng=rng)

    if reliable_talent and is_proficient and result.total - modifier < 10:
        result = RollResult(dice=result.dice, modifier=modifier, total=10 + modifier)

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


def skill_proficiency_bonus(
    proficiency_bonus: int,
    *,
    proficient: bool,
    expertise: bool = False,
    jack_of_all_trades: bool = False,
) -> int:
    """The Proficiency Bonus share a skill check adds: doubled by Expertise
    (proficient skills only), whole when proficient, half rounded down under
    Jack of All Trades when not proficient, else nothing."""
    if proficient:
        return proficiency_bonus * 2 if expertise else proficiency_bonus
    return proficiency_bonus // 2 if jack_of_all_trades else 0


def passive_perception(
    wisdom_score: int,
    proficient: bool,
    proficiency_bonus: int,
    *,
    expertise: bool = False,
    jack_of_all_trades: bool = False,
) -> int:
    """SRD 5.2 Passive Perception = 10 + Wisdom (Perception) check modifier."""
    return (
        10
        + ability_modifier(wisdom_score)
        + skill_proficiency_bonus(
            proficiency_bonus,
            proficient=proficient,
            expertise=expertise,
            jack_of_all_trades=jack_of_all_trades,
        )
    )


def ability_check(
    ability: str,
    ability_scores: dict[str, int],
    dc: int | None = None,
    advantage: bool = False,
    disadvantage: bool = False,
    *,
    rng: random.Random | None = None,
) -> SkillCheckResult:
    """Raw ability check (no skill proficiency)."""
    score = ability_scores.get(ability.lower(), 10)
    modifier = ability_modifier(score)

    if advantage and disadvantage:
        advantage = False
        disadvantage = False

    if advantage:
        result = roll_with_advantage(modifier=modifier, rng=rng)
    elif disadvantage:
        result = roll_with_disadvantage(modifier=modifier, rng=rng)
    else:
        result = roll_d20(modifier=modifier, rng=rng)

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
    *,
    rng: random.Random | None = None,
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
        result = roll_with_advantage(modifier=modifier, rng=rng)
    elif disadvantage:
        result = roll_with_disadvantage(modifier=modifier, rng=rng)
    else:
        result = roll_d20(modifier=modifier, rng=rng)

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
    "SKILL_CODE_TO_SLUG",
    "SKILL_DISPLAY_NAMES",
    "Skill",
    "SkillCheckResult",
    "ability_check",
    "contested_check",
    "passive_perception",
    "saving_throw",
    "skill_check",
    "skill_proficiency_bonus",
]
