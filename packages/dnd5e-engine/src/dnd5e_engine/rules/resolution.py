"""
Dice resolution helpers used by the v2.2 engine dispatch layer.

Pure module: zero imports from neo4j, asyncpg, redis, or the host (Neo4j/PG/Redis layers).
All DB fetching is done by the caller and passed in as parameters.
"""

from __future__ import annotations

from typing import Any

from dnd5e_engine.rules._parsing import safe_parse_json
from dnd5e_engine.rules.skills import SKILL_ABILITIES
from dnd5e_engine.types.dice import DiceOutcome


def classify_roll_type(roll_type_str: str) -> str:
    """
    Classify a free-text roll type into a standard category.
    Returns: "attack", "saving_throw", "skill_check", or "ability_check"
    """
    s = roll_type_str.lower()
    if "attack" in s:
        return "attack"
    if "saving throw" in s or "save" in s:
        return "saving_throw"

    # Check if it's a known skill
    s_cleaned = s.replace(" check", "").strip()
    normalized_skill = s_cleaned.replace(" ", "_")
    if normalized_skill in SKILL_ABILITIES:
        return "skill_check"

    # Check if it's a known ability score
    abilities = ["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"]
    if any(a in s_cleaned for a in abilities):
        return "ability_check"

    # Default fallback
    return "ability_check"


def extract_ability_from_roll_type(roll_type_str: str) -> str:
    """Extract which ability is being used for a save or check."""
    s = roll_type_str.lower()
    abilities = ["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"]
    for a in abilities:
        if a in s:
            return a

    abbreviations = {
        "str": "strength",
        "dex": "dexterity",
        "con": "constitution",
        "int": "intelligence",
        "wis": "wisdom",
        "cha": "charisma",
    }
    s_words = s.replace("-", " ").split()
    for word in s_words:
        if word in abbreviations:
            return abbreviations[word]

    return "dexterity"  # fallback


def extract_skill_from_roll_type(roll_type_str: str) -> str:
    """Extract which skill is being used."""
    s = roll_type_str.lower().replace(" check", "").strip()
    return s.replace(" ", "_")


def parse_ability_scores(db_value: Any) -> dict[str, int]:
    """Parse ability scores from database, handling multiple storage formats.

    Supports:
    - Flat properties: {str_score: 16, dex_score: 14, ...} -> builds full dict
    - JSON string: '{"strength": 16, ...}' -> parses to dict
    - Already-parsed dict: {"strength": 16, ...} -> returns as-is
    - None/empty -> returns defaults
    """
    default = {
        "strength": 10,
        "dexterity": 10,
        "constitution": 10,
        "intelligence": 10,
        "wisdom": 10,
        "charisma": 10,
    }

    if not db_value:
        return default

    # Support flat score properties (str_score, dex_score, etc.)
    if isinstance(db_value, dict) and "str_score" in db_value:
        return {
            "strength": db_value.get("str_score", 10),
            "dexterity": db_value.get("dex_score", 10),
            "constitution": db_value.get("con_score", 10),
            "intelligence": db_value.get("int_score", 10),
            "wisdom": db_value.get("wis_score", 10),
            "charisma": db_value.get("cha_score", 10),
        }

    parsed = safe_parse_json(db_value, fallback=None)
    if isinstance(parsed, dict):
        return parsed

    return default


# ── Extracted helpers ──────────────────────────────────────────────────────────


def calculate_natural_roll(
    dice: list[int],
    advantage: bool = False,
    disadvantage: bool = False,
) -> int:
    """Calculate the natural roll from dice, applying advantage/disadvantage."""
    if not (advantage or disadvantage):
        return dice[0]
    return max(dice) if advantage else min(dice)


def build_dice_outcome(
    req: Any,
    roll_total: int,
    natural_roll: int,
    modifier: int,
    dice: list[int],
    dc: int | None,
    success: bool | None,
    summary: str,
    die_size: int = 20,
) -> DiceOutcome:
    """Build a DiceOutcome with critical/fumble auto-detection.

    Args:
        req: Any object with request_id, character_id, roll_type, target_id attributes.
    """
    return DiceOutcome(
        request_id=req.request_id,
        character_id=req.character_id,
        roll_type=req.roll_type,
        target_id=req.target_id,
        roll_total=roll_total,
        natural_roll=natural_roll,
        modifier=modifier,
        dice=dice,
        dc=dc,
        success=success,
        is_critical=natural_roll == 20,
        is_fumble=natural_roll == 1,
        summary=summary,
        die_size=die_size,
    )


__all__ = [
    "build_dice_outcome",
    "calculate_natural_roll",
    "classify_roll_type",
    "extract_ability_from_roll_type",
    "extract_skill_from_roll_type",
    "parse_ability_scores",
]
