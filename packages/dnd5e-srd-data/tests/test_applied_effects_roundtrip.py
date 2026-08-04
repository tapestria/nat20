"""Round-trip fidelity for Foundry's legacy flat ``appliedEffects`` id list.

Foundry persists ``appliedEffects`` (a flat ``list[str]`` of effect ids)
alongside the structured ``effects[]`` slice on every activity kind except
``cast``. The per-kind Activity models carry it as ``applied_effects`` so
canonical → consumer is lossless; resolver behavior comes from ``effects[]``
and must not change.
"""

from __future__ import annotations

from dnd5e_srd_data import BundledAssetLoader
from dnd5e_srd_data.schema.common import SaveActivity
from tools.translators.foundry import _normalize_activity_dict


def test_schema_models_applied_effects_field():
    act = SaveActivity.model_validate({"_id": "a1", "applied_effects": ["x1", "x2"]})
    assert act.applied_effects == ["x1", "x2"]
    assert SaveActivity(_id="a2").applied_effects == []
    dumped = SaveActivity.model_validate({"_id": "a3", "applied_effects": ["y"]}).model_dump()
    assert dumped["applied_effects"] == ["y"]


def test_normalizer_maps_applied_effects_instead_of_dropping():
    normalized = _normalize_activity_dict({"appliedEffects": ["U5UciD171a5jcc7s"]})
    assert normalized == {"applied_effects": ["U5UciD171a5jcc7s"]}


def test_resilient_sphere_applied_effects_round_trip():
    """resilient-sphere's raw YAML carries a non-empty ``appliedEffects``
    (aliasing the "Enclosed in Sphere" effect id); canonical must preserve it
    and it must keep aliasing the structured ``effects[]`` slice."""
    loader = BundledAssetLoader()
    spell = loader.get_spell("resilient-sphere")
    assert spell is not None
    saves = [a for a in spell.activities if a.kind == "save"]
    assert len(saves) == 1
    assert saves[0].applied_effects == ["U5UciD171a5jcc7s"]
    assert [e.id for e in saves[0].effects] == ["U5UciD171a5jcc7s"]


def test_hunters_mark_damage_activity_applied_effects_round_trip():
    loader = BundledAssetLoader()
    spell = loader.get_spell("hunters-mark")
    assert spell is not None
    matches = [a for a in spell.activities if a.id == "dnd5eactivity000"]
    assert len(matches) == 1
    assert matches[0].kind == "damage"
    assert matches[0].applied_effects == ["hYD38IP9Meq2ArIS"]


def test_applied_effects_defaults_empty_when_upstream_ships_empty():
    """freezing-sphere's activities ship ``appliedEffects: []`` upstream —
    preserved as an empty list, not dropped."""
    loader = BundledAssetLoader()
    spell = loader.get_spell("freezing-sphere")
    assert spell is not None
    for act in spell.activities:
        assert act.applied_effects == []
