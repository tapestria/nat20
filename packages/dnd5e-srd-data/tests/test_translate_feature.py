from datetime import date
from pathlib import Path

import pytest

from tools.translators.foundry import translate_feature_yaml

PACKS = Path("raw_sources/foundry/packs/_source")
INGEST = dict(ingest_date=date(2026, 6, 4), ingest_version="foundry-translator-v1")
pytestmark = pytest.mark.skipif(not PACKS.is_dir(), reason="raw_sources/foundry not populated")


def test_rage_translates_with_activity_and_symbolic_scale():
    f = translate_feature_yaml(PACKS / "classes24/barbarian/class-features/rage.yml", **INGEST)
    assert f.slug == "rage"
    assert f.feature_type == "class_feature"
    assert f.source_slug == "barbarian"
    assert f.foundry_id == "phbbrbRage000000"
    assert any(a.kind == "utility" for a in f.activities)
    vals = [c.value for e in f.passive_effects for c in e.changes]
    assert "+@scale.barbarian.rage-damage" in vals


def test_sneak_attack_damage_activity():
    f = translate_feature_yaml(PACKS / "classes24/rogue/class-features/sneak-attack.yml", **INGEST)
    assert f.slug == "sneak-attack"
    assert any(a.kind == "damage" for a in f.activities)


def test_subclass_feature_type_and_source():
    f = translate_feature_yaml(
        PACKS / "classes24/barbarian/subclass-features/path-of-the-berserker/frenzy.yml", **INGEST
    )
    assert f.feature_type == "subclass_feature"
    assert f.source_slug == "path-of-the-berserker"


def test_metamagic_option_is_class_feature_sourced_to_sorcerer():
    f = translate_feature_yaml(
        PACKS / "classes24/sorcerer/metamagic-options/careful-spell.yml", **INGEST
    )
    assert f.feature_type == "class_feature"
    assert f.source_slug == "sorcerer"


def test_prose_only_species_trait():
    f = translate_feature_yaml(
        PACKS / "origins24/species/traits/dwarf/dwarven-resilience.yml", **INGEST
    )
    assert f.feature_type == "species_trait"
    assert f.source_slug == "dwarf"
    assert f.activities == []
    assert f.passive_effects == []


def test_second_wind_carries_top_level_uses_cap_and_recovery():
    """Second Wind's top-level ``system.uses`` (a capped, rest-recharged pool)
    survives translation into a typed ``FeatureUses``."""
    f = translate_feature_yaml(
        PACKS / "classes24/fighter/class-features/second-wind.yml", **INGEST
    )
    assert f.uses is not None
    assert f.uses.max == "@scale.fighter.second-wind"
    assert f.uses.spent == 0
    periods = {(r.period, r.type, r.formula) for r in f.uses.recovery}
    assert ("lr", "recoverAll", "") in periods
    assert ("sr", "formula", "1") in periods


def test_feature_without_uses_block_has_none_uses():
    """A prose-only trait with no ``system.uses`` serializes ``uses = None`` — not an
    empty, engine-inert block."""
    f = translate_feature_yaml(
        PACKS / "origins24/species/traits/dwarf/dwarven-resilience.yml", **INGEST
    )
    assert f.uses is None
