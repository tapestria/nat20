"""Unit tests for the canonical vs oracle cross-check."""

from tools.audit.cross_check import (
    CrossCheckFinding,
    diff_item_flat_fields,
    diff_monster_flat_fields,
)


def test_monster_no_diff_when_fields_match() -> None:
    canonical = {"hp": 7, "ac": 15, "cr": 0.25, "proficiency_bonus": 2}
    oracle = {"hp": 7, "ac": 15, "cr": 0.25, "proficiency_bonus": 2}
    assert diff_monster_flat_fields("goblin", canonical, oracle) == []


def test_monster_records_hp_disagreement() -> None:
    canonical = {"hp": 7, "ac": 15, "cr": 0.25}
    oracle = {"hp": 6, "ac": 15, "cr": 0.25}
    findings = diff_monster_flat_fields("goblin", canonical, oracle)
    assert findings == [
        CrossCheckFinding(
            slug="goblin", kind="monster", field="hp", canonical_value=7, oracle_value=6
        ),
    ]


def test_item_records_damage_dice_mismatch() -> None:
    canonical = {
        "damage_parts": [{"dice": "1d8", "damage_type": "slashing"}],
        "weight": 3.0,
        "cost_gp": 15.0,
    }
    oracle = {
        "kind": "weapon",
        "damage_dice": "1d10",
        "damage_type": "slashing",
        "weight": 3.0,
        "cost_gp": 15.0,
    }
    findings = diff_item_flat_fields("longsword", canonical, oracle)
    assert findings == [
        CrossCheckFinding(
            slug="longsword",
            kind="item",
            field="damage_dice",
            canonical_value="1d8",
            oracle_value="1d10",
        ),
    ]
