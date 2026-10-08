"""SRD 5.2 feats in the canonical corpus: each background's Origin feat, and
which feats can be taken more than once.

SRD 5.2 Character Origins: "A background gives your character a specified
Origin feat." Feats: "A feat can be taken only once unless its description
states otherwise in a "Repeatable" subsection."
"""

from __future__ import annotations

import pytest

from dnd5e_srd_data import BundledAssetLoader, FeatCategory

LOADER = BundledAssetLoader()


@pytest.mark.parametrize(
    ("background", "feat"),
    [
        ("acolyte", "magic-initiate"),
        ("criminal", "alert"),
        ("sage", "magic-initiate"),
        ("soldier", "savage-attacker"),
    ],
)
def test_a_background_names_its_origin_feat_by_its_canonical_slug(
    background: str, feat: str
) -> None:
    found = LOADER.get_background(background)
    assert found is not None
    assert found.starting_feat_slug == feat
    granted = LOADER.get_feat(feat)
    assert granted is not None
    assert granted.category is FeatCategory.ORIGIN
    # "Feat: Alert", "Feat: Magic Initiate (Cleric)", ...
    assert f"Feat: {granted.name}" in found.description


def test_exactly_the_feats_with_a_repeatable_subsection_are_repeatable() -> None:
    feats = [LOADER.get_feat(slug) for slug in LOADER.list_slugs("feats")]
    assert {f.slug for f in feats if f is not None and f.repeatable} == {
        "ability-score-improvement",
        "magic-initiate",
        "skilled",
    }
    for feat in feats:
        assert feat is not None
        assert feat.repeatable == ("Repeatable." in feat.description), feat.slug
