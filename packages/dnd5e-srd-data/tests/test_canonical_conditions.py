"""Shipped ``canonical/conditions/`` — SRD 5.2 rules glossary (C22-S01)."""

from __future__ import annotations

from dnd5e_srd_data import BundledAssetLoader
from dnd5e_srd_data.schema.condition import ConditionEffectKind

EXPECTED = {
    "blinded",
    "charmed",
    "deafened",
    "exhaustion",
    "frightened",
    "grappled",
    "incapacitated",
    "invisible",
    "paralyzed",
    "petrified",
    "poisoned",
    "prone",
    "restrained",
    "stunned",
    "unconscious",
}


def test_exactly_the_fifteen_srd_conditions_ship():
    loader = BundledAssetLoader()
    assert set(loader.list_conditions()) == EXPECTED


def test_prone_grants_advantage_to_adjacent_attackers():
    prone = BundledAssetLoader().get_condition("prone")
    assert prone is not None
    adv = [e for e in prone.effects if e.kind is ConditionEffectKind.ADVANTAGE_ATTACKS_AGAINST]
    assert adv and adv[0].value == 5


def test_implied_conditions_match_the_glossary():
    loader = BundledAssetLoader()
    assert loader.get_condition("unconscious").implies == ["incapacitated", "prone"]
    for slug in ("paralyzed", "petrified", "stunned"):
        assert loader.get_condition(slug).implies == ["incapacitated"]
    assert loader.get_condition("exhaustion").implies == []


def test_every_condition_has_provenance_and_prose():
    loader = BundledAssetLoader()
    for slug in loader.list_conditions():
        c = loader.get_condition(slug)
        assert c is not None
        assert c.provenance.license_tag == "CC-BY-4.0"
        assert c.provenance.srd_version == frozenset({"5.2"})
        assert c.description and "<" not in c.description
        assert c.effects, slug
