from datetime import date

import pytest
from pydantic import ValidationError

from dnd5e_srd_data.schema.common import Provenance, ReviewState
from dnd5e_srd_data.schema.feat import Feat, FeatCategory, FeatPrerequisite


def _prov() -> Provenance:
    return Provenance(
        source="foundry",
        source_url="x",
        ingest_date=date(2026, 5, 30),
        ingest_version="v1",
        srd_version=frozenset({"5.2"}),
    )


def test_feat_minimal_alert() -> None:
    feat = Feat(
        slug="alert",
        name="Alert",
        description="You gain the following benefits.",
        category=FeatCategory.ORIGIN,
        provenance=_prov(),
        review=ReviewState(),
    )
    assert feat.slug == "alert"
    assert feat.category is FeatCategory.ORIGIN
    assert feat.prerequisites == []
    assert feat.activities == []
    assert feat.entry_kind == "feat"


def test_feat_category_members() -> None:
    assert FeatCategory.ORIGIN == "origin"
    assert FeatCategory.GENERAL == "general"
    assert FeatCategory.FIGHTING_STYLE == "fighting_style"
    assert FeatCategory.EPIC_BOON == "epic_boon"


def test_feat_with_prerequisite() -> None:
    feat = Feat(
        slug="grappler",
        name="Grappler",
        description="d",
        category=FeatCategory.GENERAL,
        prerequisites=[FeatPrerequisite(level=4, requirement="Strength or Dexterity 13+")],
        provenance=_prov(),
        review=ReviewState(),
    )
    assert feat.prerequisites[0].level == 4
    assert feat.prerequisites[0].requirement == "Strength or Dexterity 13+"
    assert feat.prerequisites[0].feats == []


def test_feat_rejects_unknown_category() -> None:
    with pytest.raises(ValidationError):
        Feat(
            slug="x",
            name="X",
            description="d",
            category="wizardry",  # type: ignore[arg-type]
            provenance=_prov(),
            review=ReviewState(),
        )


def test_feat_prerequisite_defaults() -> None:
    pre = FeatPrerequisite()
    assert pre.level is None
    assert pre.requirement == ""
    assert pre.feats == []
