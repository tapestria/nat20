"""Every always-on class feature a class grants is that class's own document.

Foundry gives the Barbarian's and the Monk's Unarmored Defense the same
identifier; unscoped, the Monk's document overwrote the Barbarian's and a
Barbarian's granted ``unarmored-defense`` resolved to the Monk's formula.
"""

from dnd5e_srd_data.loader import BundledAssetLoader

LOADER = BundledAssetLoader()


def test_granted_class_features_with_passive_effects_belong_to_the_granting_class() -> None:
    foreign = []
    for class_slug in LOADER.list_slugs("classes"):
        cls = LOADER.get_class(class_slug)
        assert cls is not None
        for grant in cls.granted_features:
            if grant.ref_type != "feature":
                continue
            feature = LOADER.get_feature(grant.slug)
            if feature is None or feature.feature_type != "class_feature":
                continue
            if feature.passive_effects and feature.source_slug != class_slug:
                foreign.append((class_slug, grant.slug, feature.source_slug))
    assert foreign == []


def test_barbarian_and_monk_unarmored_defense_carry_their_own_formula() -> None:
    barbarian = LOADER.get_feature("unarmored-defense")
    monk = LOADER.get_feature("unarmored-defense-monk")
    assert barbarian is not None and monk is not None
    assert barbarian.source_slug == "barbarian"
    assert [c.value for p in barbarian.passive_effects for c in p.changes] == ["unarmoredBarb"]
    assert monk.source_slug == "monk"
    assert [c.value for p in monk.passive_effects for c in p.changes] == ["unarmoredMonk"]
    monk_class = LOADER.get_class("monk")
    assert monk_class is not None
    assert "unarmored-defense-monk" in {g.slug for g in monk_class.granted_features}
