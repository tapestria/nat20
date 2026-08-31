"""Shipped ``canonical/traits/`` + ``MonsterAction.mechanic`` (C22-S02)."""

from __future__ import annotations

from dnd5e_srd_data import BundledAssetLoader
from dnd5e_srd_data.schema.monster import MonsterTraitMechanic


def test_pit_fiend_magic_resistance_is_typed():
    pit_fiend = BundledAssetLoader().get_monster("pit-fiend")
    assert pit_fiend is not None
    mr = next(a for a in pit_fiend.special_abilities if a.name == "Magic Resistance")
    assert mr.mechanic is MonsterTraitMechanic.MAGIC_RESISTANCE


def test_magic_resistance_frequency_matches_the_rule_card():
    loader = BundledAssetLoader()
    carriers = [
        slug
        for slug in loader.list_slugs("monsters")
        if any(
            a.mechanic is MonsterTraitMechanic.MAGIC_RESISTANCE
            for a in loader.get_monster(slug).special_abilities
        )
    ]
    assert len(carriers) == 34


def test_traits_category_is_deduplicated_and_typed():
    loader = BundledAssetLoader()
    slugs = loader.list_slugs("traits")
    # = every distinct special_abilities slug across the shipped SRD monsters (2026-08-30 corpus)
    assert len(slugs) == len(set(slugs)) and len(slugs) == 102
    mr = loader.get_trait("magic-resistance")
    assert mr is not None
    assert mr.mechanic is MonsterTraitMechanic.MAGIC_RESISTANCE
    assert "[[lookup" not in mr.description
    assert mr.provenance.license_tag == "CC-BY-4.0"
    assert loader.get_trait("amphibious").mechanic is MonsterTraitMechanic.AMPHIBIOUS
    assert loader.get_trait("fear-aura").mechanic is None  # prose fallback
    assert loader.get_trait("demonic-restoration").mechanic is MonsterTraitMechanic.RESTORATION
