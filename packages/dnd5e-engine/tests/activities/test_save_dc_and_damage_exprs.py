"""Direct pins on ``activities/save.py::_resolve_dc`` and the damage-expression
builders in ``activities/dice.py`` / ``activities/formula.py``.

The end-to-end scenarios reach these only through the corpus' common shapes
(spellcasting DC, automatic ``{n}d{d}`` formulas); the flat-DC, custom-formula
and scaling-token branches are pinned here.
"""

from __future__ import annotations

import random

import pytest
from dnd5e_srd_data.loader import BundledAssetLoader
from dnd5e_srd_data.schema.common import (
    DamageCustomBlock,
    DamagePart,
    DamagePartBlock,
    DamageScalingBlock,
    SaveActivity,
)

from dnd5e_engine.activities.context import ActivityResolutionContext
from dnd5e_engine.activities.dice import damage_part_to_expr
from dnd5e_engine.activities.formula import resolve_damage_block
from dnd5e_engine.activities.save import _resolve_dc
from dnd5e_engine.types.combat import Combatant


def _ctx(**overrides: object) -> ActivityResolutionContext:
    kwargs: dict[str, object] = dict(
        rng=random.Random(1),
        caster=Combatant(
            entity_id="char:wiz",
            entity_type="Character",
            name="Wiz",
            initiative=10,
            hp_current=10,
            hp_max=10,
        ),
        targets=[],
        event_emitter=lambda ev: None,
        caster_abilities={"str": 10, "dex": 10, "con": 10, "int": 16, "wis": 10, "cha": 10},
        caster_proficiency_bonus=2,
        spellcasting_ability="int",
    )
    kwargs.update(overrides)
    return ActivityResolutionContext(**kwargs)  # type: ignore[arg-type]


@pytest.fixture(scope="module")
def fireball_save() -> SaveActivity:
    spell = BundledAssetLoader().get_spell("fireball")
    assert spell is not None
    activity = next(a for a in spell.activities if a.kind == "save")
    assert isinstance(activity, SaveActivity)
    return activity


def _with_dc(activity: SaveActivity, calculation: str, formula: str = "") -> SaveActivity:
    dc = activity.save.dc.model_copy(update={"calculation": calculation, "formula": formula})
    return activity.model_copy(update={"save": activity.save.model_copy(update={"dc": dc})})


# ── _resolve_dc ──────────────────────────────────────────────────────────────


def test_spellcasting_dc_is_8_plus_prof_plus_mod(fireball_save: SaveActivity) -> None:
    assert _resolve_dc(fireball_save, _ctx()) == 8 + 2 + 3


def test_spellcasting_dc_without_a_casting_ability_is_loud(fireball_save: SaveActivity) -> None:
    with pytest.raises(ValueError, match="spellcasting ability"):
        _resolve_dc(fireball_save, _ctx(spellcasting_ability=None))


def test_flat_dc_resolves_the_formula(fireball_save: SaveActivity) -> None:
    assert _resolve_dc(_with_dc(fireball_save, "flat", "13"), _ctx()) == 13


def test_flat_dc_resolves_roll_data_tokens(fireball_save: SaveActivity) -> None:
    # @prof folds to the caster's proficiency bonus before evaluation.
    assert _resolve_dc(_with_dc(fireball_save, "flat", "10 + @prof"), _ctx()) == 12


def test_unknown_dc_calculation_is_loud(fireball_save: SaveActivity) -> None:
    with pytest.raises(ValueError, match="not resolvable"):
        _resolve_dc(_with_dc(fireball_save, "mystery"), _ctx())


def test_save_dc_override_bypasses_the_calculation(fireball_save: SaveActivity) -> None:
    assert _resolve_dc(_with_dc(fireball_save, "mystery"), _ctx(save_dc_override=18)) == 18


# ── damage_part_to_expr ──────────────────────────────────────────────────────


def test_weapon_damage_part_passes_its_dice_string_through() -> None:
    assert damage_part_to_expr(DamagePart(dice="2d6+3", damage_type="slashing")) == "2d6+3"


def test_activity_block_builds_the_automatic_formula() -> None:
    assert damage_part_to_expr(DamagePartBlock(number=2, denomination=6, bonus="3")) == "2d6+3"


def test_activity_block_with_only_a_bonus_is_the_bare_bonus() -> None:
    assert damage_part_to_expr(DamagePartBlock(bonus="5")) == "5"


def test_activity_block_custom_formula_wins_when_enabled() -> None:
    block = DamagePartBlock(
        number=2, denomination=6, custom=DamageCustomBlock(enabled=True, formula="1d4")
    )
    assert damage_part_to_expr(block) == "1d4"


# ── resolve_damage_block ─────────────────────────────────────────────────────


def test_scaling_formula_tokens_are_resolved_off_the_context() -> None:
    block = DamagePartBlock(number=1, denomination=8, scaling=DamageScalingBlock(formula="@prof"))
    resolved = resolve_damage_block(block, _ctx(), ability="int")
    assert resolved.scaling.formula == "2"
    assert resolved.number == 1  # untouched fields survive the copy


def test_block_without_tokens_is_returned_unchanged() -> None:
    block = DamagePartBlock(number=1, denomination=8, bonus="2")
    assert resolve_damage_block(block, _ctx(), ability="int") is block
