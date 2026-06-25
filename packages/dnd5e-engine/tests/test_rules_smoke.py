"""Smoke test — rules modules importable and basic operations work."""

from __future__ import annotations


def test_roll_d20_returns_in_range():
    from dnd5e_engine.rules.dice import roll_d20

    r = roll_d20()
    assert 1 <= r.total <= 20


def test_ability_modifier_known_values():
    from dnd5e_engine.rules.dice import ability_modifier

    assert ability_modifier(10) == 0
    assert ability_modifier(14) == 2
    assert ability_modifier(20) == 5


def test_all_moved_rules_modules_importable():
    """Smoke: every Phase-3-moved rules module imports without raising."""
    import importlib

    for mod in [
        "dnd5e_engine.rules.dice",
        "dnd5e_engine.rules.equipment",
        "dnd5e_engine.rules.conditions",
        "dnd5e_engine.rules.spells",
        "dnd5e_engine.rules.skills",
        "dnd5e_engine.rules.combat",
        "dnd5e_engine.rules.gambits",
        "dnd5e_engine.rules.combat_data",
        "dnd5e_engine.rules.combat_helpers",
        "dnd5e_engine.rules.resolution",
        "dnd5e_engine.rules.effects",
    ]:
        importlib.import_module(mod)


def test_saving_throw_proficient_adds_bonus(monkeypatch):
    # Pin d20 to 10 for determinism.
    import dnd5e_engine.rules.dice as dice_mod

    monkeypatch.setattr(dice_mod.random, "randint", lambda a, b: 10)

    from dnd5e_engine.rules.skills import saving_throw

    result = saving_throw(
        ability="wisdom",
        ability_scores={"wisdom": 14},  # +2 modifier
        proficient_saves=["wisdom"],
        proficiency_bonus=3,
        dc=15,
    )
    assert result.ability == "wisdom"
    assert result.is_proficient is True
    # 10 (roll) + 2 (WIS mod) + 3 (prof) = 15
    assert result.roll.total == 15
    assert result.total_modifier == 5
    assert result.success is True


def test_saving_throw_non_proficient_no_bonus(monkeypatch):
    import dnd5e_engine.rules.dice as dice_mod

    monkeypatch.setattr(dice_mod.random, "randint", lambda a, b: 8)

    from dnd5e_engine.rules.skills import saving_throw

    result = saving_throw(
        ability="dexterity",
        ability_scores={"dexterity": 12},  # +1
        proficient_saves=["wisdom"],
        proficiency_bonus=3,
        dc=12,
    )
    assert result.is_proficient is False
    assert result.total_modifier == 1
    assert result.roll.total == 9
    assert result.success is False
