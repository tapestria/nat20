"""Behavioral tests for the host-facing parsing/classification helpers.

Covers ``rules/_parsing.py`` and ``rules/resolution.py``. These sit on the
seam where a host hands raw store values to the engine, so the contract that
matters is *degradation*: an unparseable property must produce a documented
fallback rather than an exception in the middle of resolving a roll.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from dnd5e_engine.rules._parsing import safe_parse_json
from dnd5e_engine.rules.resolution import (
    build_dice_outcome,
    calculate_natural_roll,
    classify_roll_type,
    extract_ability_from_roll_type,
    extract_skill_from_roll_type,
    parse_ability_scores,
)

DEFAULT_SCORES = {
    "strength": 10,
    "dexterity": 10,
    "constitution": 10,
    "intelligence": 10,
    "wisdom": 10,
    "charisma": 10,
}


# ---------------------------------------------------------------------------
# safe_parse_json
# ---------------------------------------------------------------------------


def test_safe_parse_json_decodes_json_objects_and_arrays() -> None:
    assert safe_parse_json('{"a": 1}') == {"a": 1}
    assert safe_parse_json("[1, 2, 3]") == [1, 2, 3]


def test_safe_parse_json_falls_back_to_python_literals() -> None:
    """Stores that persist ``repr()`` output emit single-quoted literals, which
    are not valid JSON — the literal_eval fallback rescues them."""
    assert safe_parse_json("{'a': 1}") == {"a": 1}
    assert safe_parse_json("('x', 'y')") == ("x", "y")


def test_safe_parse_json_passes_through_non_strings_untouched() -> None:
    """Already-parsed values must not be re-parsed."""
    parsed = {"a": 1}

    assert safe_parse_json(parsed) is parsed
    assert safe_parse_json(7) == 7
    assert safe_parse_json(True) is True


@pytest.mark.parametrize("value", [None, "", "not json at all", "{unclosed", "1 + 1"])
def test_safe_parse_json_returns_fallback_for_unparseable(value: Any) -> None:
    sentinel = object()

    assert safe_parse_json(value, fallback=sentinel) is sentinel


def test_safe_parse_json_default_fallback_is_none() -> None:
    assert safe_parse_json("{bad") is None


# ---------------------------------------------------------------------------
# classify_roll_type
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Attack", "attack"),
        ("melee weapon attack", "attack"),
        ("Dexterity Saving Throw", "saving_throw"),
        ("wisdom save", "saving_throw"),
        ("Stealth check", "skill_check"),
        ("sleight of hand", "skill_check"),
        ("Perception", "skill_check"),
        ("Strength check", "ability_check"),
        ("constitution", "ability_check"),
        ("something entirely unknown", "ability_check"),
    ],
)
def test_classify_roll_type(raw: str, expected: str) -> None:
    assert classify_roll_type(raw) == expected


def test_classify_prefers_attack_over_skill_wording() -> None:
    """'attack' is checked first — an attack roll must never be classified as
    a skill check just because a skill name appears in the label."""
    assert classify_roll_type("Stealth attack") == "attack"


def test_classify_prefers_save_over_skill_wording() -> None:
    assert classify_roll_type("Athletics saving throw") == "saving_throw"


def test_classify_multiword_skill_normalizes_spaces() -> None:
    assert classify_roll_type("animal handling check") == "skill_check"


# ---------------------------------------------------------------------------
# extract_ability_from_roll_type
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Strength saving throw", "strength"),
        ("DEXTERITY check", "dexterity"),
        ("constitution save", "constitution"),
        ("intelligence", "intelligence"),
        ("Wisdom", "wisdom"),
        ("charisma check", "charisma"),
    ],
)
def test_extract_ability_matches_full_names(raw: str, expected: str) -> None:
    assert extract_ability_from_roll_type(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("STR save", "strength"),
        ("dex save", "dexterity"),
        ("con save", "constitution"),
        ("int save", "intelligence"),
        ("wis save", "wisdom"),
        ("cha save", "charisma"),
        ("cha-save", "charisma"),  # hyphens are split like spaces
    ],
)
def test_extract_ability_matches_abbreviations(raw: str, expected: str) -> None:
    assert extract_ability_from_roll_type(raw) == expected


def test_extract_ability_abbreviation_must_be_a_whole_word() -> None:
    """'constitution' contains 'con', but a bare substring must not win — the
    abbreviation table only matches whole words, so an unmatched label falls
    through to the documented dexterity default."""
    assert extract_ability_from_roll_type("contortion check") == "dexterity"


def test_extract_ability_defaults_to_dexterity() -> None:
    assert extract_ability_from_roll_type("mystery roll") == "dexterity"


# ---------------------------------------------------------------------------
# extract_skill_from_roll_type
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Stealth check", "stealth"),
        ("Sleight of Hand check", "sleight_of_hand"),
        ("  Animal Handling  ", "animal_handling"),
        ("PERCEPTION", "perception"),
    ],
)
def test_extract_skill_normalizes_to_table_keys(raw: str, expected: str) -> None:
    """The returned key must be usable directly against SKILL_ABILITIES."""
    from dnd5e_engine.rules.skills import SKILL_ABILITIES

    assert extract_skill_from_roll_type(raw) == expected
    assert expected in SKILL_ABILITIES


# ---------------------------------------------------------------------------
# parse_ability_scores
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("empty", [None, "", {}, 0])
def test_parse_ability_scores_defaults_on_empty(empty: Any) -> None:
    assert parse_ability_scores(empty) == DEFAULT_SCORES


def test_parse_ability_scores_expands_flat_score_properties() -> None:
    """Flat ``*_score`` node properties expand to the full named dict."""
    result = parse_ability_scores(
        {
            "str_score": 16,
            "dex_score": 14,
            "con_score": 15,
            "int_score": 8,
            "wis_score": 12,
            "cha_score": 10,
        }
    )

    assert result == {
        "strength": 16,
        "dexterity": 14,
        "constitution": 15,
        "intelligence": 8,
        "wisdom": 12,
        "charisma": 10,
    }


def test_parse_ability_scores_flat_form_defaults_absent_scores() -> None:
    """A partial flat bag must still yield all six abilities."""
    result = parse_ability_scores({"str_score": 18})

    assert result["strength"] == 18
    assert result["dexterity"] == 10
    assert result["charisma"] == 10


def test_parse_ability_scores_decodes_json_strings() -> None:
    result = parse_ability_scores('{"strength": 16, "dexterity": 14}')

    assert result == {"strength": 16, "dexterity": 14}


def test_parse_ability_scores_passes_through_named_dicts() -> None:
    scores = {"strength": 16, "dexterity": 14}

    assert parse_ability_scores(scores) == scores


def test_parse_ability_scores_falls_back_on_unparseable_string() -> None:
    assert parse_ability_scores("{not json") == DEFAULT_SCORES


def test_parse_ability_scores_falls_back_on_non_mapping_json() -> None:
    """A JSON array parses fine but is not an ability bag."""
    assert parse_ability_scores("[16, 14, 15]") == DEFAULT_SCORES


# ---------------------------------------------------------------------------
# calculate_natural_roll
# ---------------------------------------------------------------------------


def test_natural_roll_uses_first_die_when_flat() -> None:
    assert calculate_natural_roll([7, 19]) == 7


def test_natural_roll_advantage_takes_the_higher_die() -> None:
    assert calculate_natural_roll([7, 19], advantage=True) == 19


def test_natural_roll_disadvantage_takes_the_lower_die() -> None:
    assert calculate_natural_roll([7, 19], disadvantage=True) == 7


def test_natural_roll_advantage_and_disadvantage_together_take_the_max() -> None:
    """Both flags set is a caller bug; the implementation resolves it to
    advantage rather than raising. Pinned so a change is deliberate."""
    assert calculate_natural_roll([7, 19], advantage=True, disadvantage=True) == 19


# ---------------------------------------------------------------------------
# build_dice_outcome
# ---------------------------------------------------------------------------


@dataclass
class _Req:
    request_id: str = "req-1"
    character_id: str = "char:hero"
    roll_type: str = "Perception check"
    target_id: str | None = None


def test_build_dice_outcome_copies_request_identity() -> None:
    outcome = build_dice_outcome(
        _Req(target_id="npc:goblin"),
        roll_total=18,
        natural_roll=15,
        modifier=3,
        dice=[15],
        dc=12,
        success=True,
        summary="Perception check: 18 vs DC 12 — Success!",
    )

    assert outcome.request_id == "req-1"
    assert outcome.character_id == "char:hero"
    assert outcome.roll_type == "Perception check"
    assert outcome.target_id == "npc:goblin"
    assert outcome.roll_total == 18
    assert outcome.dc == 12
    assert outcome.success is True
    assert outcome.die_size == 20


def test_build_dice_outcome_flags_natural_twenty_as_critical() -> None:
    outcome = build_dice_outcome(
        _Req(),
        roll_total=25,
        natural_roll=20,
        modifier=5,
        dice=[20],
        dc=15,
        success=True,
        summary="",
    )

    assert outcome.is_critical is True
    assert outcome.is_fumble is False


def test_build_dice_outcome_flags_natural_one_as_fumble() -> None:
    outcome = build_dice_outcome(
        _Req(),
        roll_total=6,
        natural_roll=1,
        modifier=5,
        dice=[1],
        dc=15,
        success=False,
        summary="",
    )

    assert outcome.is_fumble is True
    assert outcome.is_critical is False


def test_build_dice_outcome_crit_detection_uses_the_natural_die_not_the_total() -> None:
    """A modifier that pushes the total to 20 must not read as a crit."""
    outcome = build_dice_outcome(
        _Req(),
        roll_total=20,
        natural_roll=12,
        modifier=8,
        dice=[12],
        dc=None,
        success=None,
        summary="",
    )

    assert outcome.is_critical is False
    assert outcome.is_fumble is False
    assert outcome.success is None


def test_build_dice_outcome_non_d20_dice_never_crit() -> None:
    """Damage rolls reuse this builder with die_size set; a 20 on a d20-sized
    die is only meaningful for d20 rolls, so callers pass the real die size."""
    outcome = build_dice_outcome(
        _Req(),
        roll_total=7,
        natural_roll=7,
        modifier=0,
        dice=[3, 4],
        dc=None,
        success=None,
        summary="2d6 damage",
        die_size=6,
    )

    assert outcome.die_size == 6
    assert outcome.is_critical is False
    assert outcome.dice == [3, 4]
