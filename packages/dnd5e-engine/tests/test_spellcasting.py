"""Pure spell-slot derivation (``dnd5e_engine.spellcasting``). SRD 5.2 ground truth:
"a level 3 Wizard has four level 1 spell slots and two level 2 slots"; Multiclass
Spellcaster table (character-creation.yml:784) == Foundry SPELL_SLOT_TABLE; Pact
Magic: "when you're a level 5 Warlock, you have two level 3 spell slots"."""

from __future__ import annotations

import pytest

from dnd5e_engine.spellcasting import (
    PACT_SLOT_TABLE,
    SPELL_SLOT_TABLE,
    count_scales_with_cast_level,
    derive_pact_slots,
    derive_spell_slots,
    effective_caster_level,
    multiclass_caster_level,
    resolve_target_count,
    slots_for_caster_level,
)


def test_tables_have_twenty_rows():
    assert len(SPELL_SLOT_TABLE) == 20
    assert len(PACT_SLOT_TABLE) == 20


@pytest.mark.parametrize(
    ("level", "expected"),
    [
        (1, {1: 2}),
        (3, {1: 4, 2: 2}),  # SRD 5.2 worked example
        (5, {1: 4, 2: 3, 3: 2}),
        (20, {1: 4, 2: 3, 3: 3, 4: 3, 5: 3, 6: 2, 7: 2, 8: 1, 9: 1}),
    ],
)
def test_full_caster_rows(level, expected):
    assert derive_spell_slots("wizard", "full", level) == expected


@pytest.mark.parametrize(
    ("level", "expected"),
    [
        (1, {1: 2}),  # R1: half rounds UP — a level-1 Paladin has slots in SRD 5.2
        (2, {1: 2}),
        (3, {1: 3}),
        (5, {1: 4, 2: 2}),
        (9, {1: 4, 2: 3, 3: 2}),
        (20, {1: 4, 2: 3, 3: 3, 4: 3, 5: 2}),
    ],
)
def test_half_caster_rows(level, expected):
    assert derive_spell_slots("paladin", "half", level) == expected


def test_third_caster_rounds_down_and_starts_empty():
    assert derive_spell_slots("fighter", "third", 1) == {}
    assert derive_spell_slots("fighter", "third", 2) == {}
    assert derive_spell_slots("fighter", "third", 3) == {1: 2}


def test_pact_and_none_progressions_yield_no_spellcasting_slots():
    assert derive_spell_slots("warlock", "pact", 5) == {}
    assert derive_spell_slots("fighter", "none", 20) == {}


@pytest.mark.parametrize(
    ("level", "expected"),
    [
        (1, {1: 1}),
        (2, {1: 2}),
        (3, {2: 2}),
        (5, {3: 2}),
        (9, {5: 2}),
        (11, {5: 3}),
        (17, {5: 4}),
        (20, {5: 4}),
    ],
)
def test_pact_slots(level, expected):
    assert derive_pact_slots(level) == expected


def test_level_out_of_range_rejected():
    with pytest.raises(ValueError):
        derive_spell_slots("wizard", "full", 0)
    with pytest.raises(ValueError):
        derive_spell_slots("wizard", "full", 21)
    with pytest.raises(ValueError):
        derive_pact_slots(0)


def test_effective_caster_level_rounding():
    assert effective_caster_level("full", 7) == 7
    assert effective_caster_level("half", 7) == 4  # ceil(3.5)
    assert effective_caster_level("third", 7) == 2  # floor(2.33)
    assert effective_caster_level("pact", 7) == 0
    assert effective_caster_level("none", 7) == 0


def test_multiclass_caster_level_rounds_per_class_then_sums():
    """R2: Paladin 2 -> ceil(1) = 1, Wizard 3 -> 3 => 4 (C17-S03); Paladin 3 / Ranger 3
    => 2 + 2 = 4, NOT ceil(6/2) = 3; Warlock levels never count."""
    assert multiclass_caster_level({"paladin": ("half", 2), "wizard": ("full", 3)}) == 4
    assert multiclass_caster_level({"paladin": ("half", 3), "ranger": ("half", 3)}) == 4
    assert multiclass_caster_level({"warlock": ("pact", 5), "wizard": ("full", 2)}) == 2
    assert multiclass_caster_level({"fighter": ("none", 10)}) == 0


def test_slots_for_caster_level_zero_is_empty():
    assert slots_for_caster_level(0) == {}
    assert slots_for_caster_level(4) == {1: 4, 2: 3}


@pytest.mark.parametrize(
    ("formula", "cast_level", "expected"),
    [
        ("2 + @item.level", 1, 3),  # Magic Missile: three darts
        ("2 + @item.level", 3, 5),
        ("@item.level - 1", 2, 1),  # Hold Person at base level: one Humanoid
        ("@item.level - 1", 4, 3),
        ("3", 9, 3),
        ("", 1, None),
        ("   ", 1, None),
    ],
)
def test_resolve_target_count(formula, cast_level, expected):
    assert resolve_target_count(formula, cast_level=cast_level) == expected


def test_resolve_target_count_floors_at_one_and_rejects_foreign_tokens():
    assert resolve_target_count("@item.level - 5", cast_level=1) == 1
    with pytest.raises(ValueError):
        resolve_target_count("@abilities.cha.mod + 1", cast_level=1)
    with pytest.raises(ValueError):
        resolve_target_count("__import__('os')", cast_level=1)


@pytest.mark.parametrize(
    ("count_formula", "expected"),
    [
        ("2 + @item.level", True),  # Magic Missile: darts scale with cast level
        ("@item.level - 1", True),  # Hold Person: extra Humanoids scale with cast level
        ("1", False),  # fixed single-target schema marker (Hex, Hunter's Mark, Wall of Fire, ...)
        ("", False),
        ("  ", False),
    ],
)
def test_count_scales_with_cast_level(count_formula, expected):
    assert count_scales_with_cast_level(count_formula) is expected
