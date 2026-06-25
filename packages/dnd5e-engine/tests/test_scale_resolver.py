"""Tests for the pure ScaleValue resolver (Task 2).

SPIKE findings (real tokens from canonical/features/*.json, owner docs via
BundledAssetLoader):

Match rule for ``@scale.<owner>.<key>[.<suffix>]``:
  * ``<owner>`` resolves against get_class | get_subclass | get_species (in that
    order). The owner space includes subclasses (Land druid) + species
    (Dragonborn), not just classes.
  * Walk the owner doc's ``advancement[]`` for entries with
    ``type == AdvancementType.SCALE_VALUE`` carrying ``configuration.scale``.
  * ``<key>`` matches when ``configuration.identifier == key`` OR
    ``slugify(advancement.title) == key`` (Sneak Attack has an EMPTY identifier
    and is reached only via the title slug).
  * Levels in ``configuration.scale`` are sparse — pick the entry at the highest
    level <= target level.

Scale value / suffix semantics (``configuration.type``):
  * ``number``  -> entry ``{value}``; bare / ``.value`` -> int value.
  * ``dice``    -> entry ``{number, faces}``; bare -> dice expr string
    (``f"{number}d{faces}"`` when number set, else ``f"d{faces}"`` when number is
    None, e.g. Monk Martial Arts Die); ``.number`` -> int dice count;
    ``.die``    -> die string ``f"d{faces}"``.
  * ``distance`` -> entry ``{value}``; bare -> int value (Paladin aura).

UNRESOLVED set (owner not on any class/subclass/species doc -> None, logged):
  * ``@scale.channel-divinity-cleric.spark`` (feature-specific scale).
"""

from __future__ import annotations

import random

import pytest
from dnd5e_srd_data.loader import BundledAssetLoader

from dnd5e_engine.activities.context import ActivityResolutionContext
from dnd5e_engine.activities.formula import resolve_roll_data
from dnd5e_engine.activities.scale import build_scale_values, resolve_scale_value
from dnd5e_engine.types.combat import Combatant

L = BundledAssetLoader()


def _ctx(**kw: object) -> ActivityResolutionContext:
    caster = Combatant(
        entity_id="char:aaaaaaaaaaaa",
        entity_type="Character",
        name="PC",
        initiative=10,
        hp_current=20,
        attack_bonus=5,
        character_level=5,
    )
    params: dict[str, object] = dict(
        rng=random.Random(1),
        caster=caster,
        targets=[],
        event_emitter=lambda e: None,
        caster_abilities={a: 10 for a in ("str", "dex", "con", "int", "wis", "cha")},
        caster_proficiency_bonus=3,
    )
    params.update(kw)
    return ActivityResolutionContext(**params)  # type: ignore[arg-type]


def test_rage_damage_number_scale_at_l5() -> None:
    # number scale {1:2, 9:3, 16:4} -> +2 at level 5 (highest <= 5 is level 1)
    assert resolve_scale_value("barbarian", "rage-damage", level=5, loader=L) == 2


def test_rage_damage_number_scale_at_l9() -> None:
    assert resolve_scale_value("barbarian", "rage-damage", level=9, loader=L) == 3


def test_rage_damage_number_scale_at_l16() -> None:
    assert resolve_scale_value("barbarian", "rage-damage", level=16, loader=L) == 4


def test_sneak_attack_dice_scale_bare_at_l5() -> None:
    # dice scale, identifier is empty -> matched via slugify(title)=="sneak-attack"
    # L5 entry: {number: 3, faces: 6} -> bare returns the full dice expr
    assert resolve_scale_value("rogue", "sneak-attack", level=5, loader=L) == "3d6"


def test_sneak_attack_dice_scale_number_suffix() -> None:
    # ``.number`` selects the dice count as an int
    assert resolve_scale_value("rogue", "sneak-attack", level=5, loader=L, suffix="number") == 3


def test_monk_die_bare_with_no_count() -> None:
    # Martial Arts Die: dice scale with number=None -> bare returns just the die
    assert resolve_scale_value("monk", "die", level=5, loader=L) == "d8"


def test_bard_inspiration_die_suffix() -> None:
    # ``.die`` suffix returns the die string
    assert resolve_scale_value("bard", "inspiration", level=5, loader=L, suffix="die") == "d8"


def test_dragonborn_species_owner() -> None:
    # owner space includes species: Dragonborn Breath Weapon dice scale at L5
    assert resolve_scale_value("dragonborn", "breath", level=5, loader=L) == "2d10"


def test_land_subclass_owner() -> None:
    # owner space includes subclasses: Land druid Lands Aid dice scale at L3
    assert resolve_scale_value("land", "lands-aid", level=3, loader=L) == "2d6"


def test_paladin_aura_distance_scale() -> None:
    # distance scale {6:10, 18:30} -> 10 at level 6
    assert resolve_scale_value("paladin", "aura", level=6, loader=L) == 10


def test_below_first_scale_level_returns_none() -> None:
    # rage-damage starts at level 1; level 0 has no entry <= it
    assert resolve_scale_value("barbarian", "rage-damage", level=0, loader=L) is None


def test_unresolved_owner_returns_none() -> None:
    # channel-divinity-cleric is a feature-specific scale, not on any owner doc
    assert resolve_scale_value("channel-divinity-cleric", "spark", level=5, loader=L) is None


def test_unresolved_key_returns_none() -> None:
    assert resolve_scale_value("barbarian", "no-such-key", level=5, loader=L) is None


def test_build_scale_values_collects_class_subclass_species() -> None:
    # The pure seam helper resolves the caster's owner docs and returns a flat
    # {full-suffix: value} map keyed by the dotted token suffix.
    sv = build_scale_values(
        class_slug="barbarian",
        subclass_slug=None,
        species_slug="dragonborn",
        level=5,
        loader=L,
    )
    # class scale (number, bare)
    assert sv["barbarian.rage-damage"] == 2
    # species scale (dice, bare)
    assert sv["dragonborn.breath"] == "2d10"


def test_build_scale_values_includes_dice_suffix_variants() -> None:
    sv = build_scale_values(
        class_slug="rogue",
        subclass_slug=None,
        species_slug=None,
        level=5,
        loader=L,
    )
    assert sv["rogue.sneak-attack"] == "3d6"
    assert sv["rogue.sneak-attack.number"] == 3


def test_build_scale_values_omits_unresolvable_owner() -> None:
    # an absent class/subclass/species slug contributes nothing (no crash)
    sv = build_scale_values(
        class_slug="barbarian",
        subclass_slug="no-such-subclass",
        species_slug=None,
        level=5,
        loader=L,
    )
    assert any(k.startswith("barbarian.") for k in sv)
    assert not any(k.startswith("no-such-subclass.") for k in sv)


# --- formula.py @scale / @classes token substitution (wiring) ---


def test_formula_number_scale_substitutes_int() -> None:
    # Rage's mwak damage bonus formula: "+@scale.barbarian.rage-damage" -> "+2"
    ctx = _ctx(scale_values={"barbarian.rage-damage": 2})
    assert resolve_roll_data("+@scale.barbarian.rage-damage", ctx) == "+2"


def test_formula_dice_scale_substitutes_expr_string() -> None:
    # Sneak Attack's damage formula "@scale.rogue.sneak-attack" -> "3d6"
    ctx = _ctx(scale_values={"rogue.sneak-attack": "3d6"})
    assert resolve_roll_data("@scale.rogue.sneak-attack", ctx) == "3d6"


def test_formula_dice_scale_number_suffix_substitutes_count() -> None:
    # frenzy-style "(@scale.rogue.sneak-attack.number)d6" -> "(3)d6"
    ctx = _ctx(scale_values={"rogue.sneak-attack.number": 3})
    assert resolve_roll_data("(@scale.rogue.sneak-attack.number)d6", ctx) == "(3)d6"


def test_formula_classes_levels_substitutes_int() -> None:
    # Second Wind heal "@classes.fighter.levels" -> the fighter level
    ctx = _ctx(class_levels={"fighter": 5})
    assert resolve_roll_data("@classes.fighter.levels", ctx) == "5"


def test_formula_unresolved_scale_token_raises() -> None:
    ctx = _ctx(scale_values={})
    with pytest.raises(ValueError, match="Unresolved @scale token"):
        resolve_roll_data("@scale.barbarian.rage-damage", ctx)


def test_formula_unresolved_classes_levels_raises() -> None:
    ctx = _ctx(class_levels={})
    with pytest.raises(ValueError, match="Unresolved @classes levels token"):
        resolve_roll_data("@classes.fighter.levels", ctx)
