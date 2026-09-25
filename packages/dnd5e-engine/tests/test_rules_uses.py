"""rules/uses.py — the limited-use ``uses.max`` grammar of the SRD corpus."""

from __future__ import annotations

import pytest

from dnd5e_engine.rules.uses import UsesRollData, evaluate_uses_formula

ROLL_DATA = UsesRollData(
    proficiency_bonus=3,
    ability_modifiers={"str": 0, "dex": 2, "con": 1, "int": 0, "wis": -1, "cha": 3},
    class_levels={"paladin": 2, "fighter": 5},
    scale_values={"fighter.second-wind": 3, "monk.die": "d6"},
)


@pytest.mark.parametrize(
    ("expr", "expected"),
    [
        ("1", 1),
        ("20", 20),
        ("@prof", 3),
        ("max(1, @abilities.cha.mod)", 3),
        ("max(1,@abilities.wis.mod)", 1),
        ("(max(1,@abilities.cha.mod))", 3),
        ("5 * @classes.paladin.levels", 10),
        ("@scale.fighter.second-wind", 3),
        ("@classes.fighter.levels + @prof", 8),
        ("min(2, @prof)", 2),
        ("-@prof + 4", 1),
    ],
)
def test_evaluates_the_corpus_grammar(expr: str, expected: int) -> None:
    assert evaluate_uses_formula(expr, ROLL_DATA) == expected


@pytest.mark.parametrize(
    "expr",
    [
        "@scale.monk.die",
        "@classes.wizard.levels",
        "@item.uses.spent",
        "2d6",
        "floor(@prof / 2)",
        "@prof ** 2",
        "max(@prof)",
        "__import__('os')",
        "",
    ],
)
def test_anything_else_is_unresolved(expr: str) -> None:
    assert evaluate_uses_formula(expr, ROLL_DATA) is None


def test_prof_needs_a_proficiency_bonus() -> None:
    assert evaluate_uses_formula("@prof", UsesRollData()) is None
