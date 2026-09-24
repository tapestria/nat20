"""The translator's class-scoped feature slugs (plan R10)."""

from pathlib import Path

from tools.translators.foundry import _feature_slug

_CLASSES = Path("raw_sources/foundry/packs/_source/classes24")


def test_monk_unarmored_defense_gets_a_class_scoped_slug() -> None:
    doc = {"system": {"identifier": "unarmored-defense"}}
    monk = _CLASSES / "monk" / "class-features" / "unarmored-defense.yml"
    barbarian = _CLASSES / "barbarian" / "class-features" / "unarmored-defense.yml"
    assert _feature_slug(doc, monk) == "unarmored-defense-monk"
    assert _feature_slug(doc, barbarian) == "unarmored-defense"


def test_every_other_feature_keeps_its_identifier() -> None:
    extra = {"system": {"identifier": "extra-attack"}}
    assert _feature_slug(extra, _CLASSES / "monk" / "class-features" / "extra-attack.yml") == (
        "extra-attack"
    )
    toughness = {"system": {"identifier": "dwarven-toughness"}}
    species = Path(
        "raw_sources/foundry/packs/_source/origins24/species/traits/dwarf/dwarven-toughness.yml"
    )
    assert _feature_slug(toughness, species) == "dwarven-toughness"
