from datetime import date
from pathlib import Path

import pytest

from dnd5e_srd_data import Feat, FeatCategory, UtilityActivity
from tools.translators.foundry import translate_feat_yaml

PACKS = Path("raw_sources/foundry/packs/_source")
pytestmark = pytest.mark.skipif(not PACKS.is_dir(), reason="raw_sources/foundry not populated")

FEATS = (
    Path(__file__).resolve().parents[1]
    / "raw_sources"
    / "foundry"
    / "packs"
    / "_source"
    / "feats24"
)


def _translate(subdir: str, name: str) -> Feat:
    return translate_feat_yaml(
        yaml_path=FEATS / subdir / name,
        ingest_date=date(2026, 5, 30),
        ingest_version="foundry-translator-v1",
    )


def test_translates_origin_feat() -> None:
    feat = _translate("origin-feats", "alert.yml")
    assert isinstance(feat, Feat)
    assert feat.slug == "alert"
    assert feat.name == "Alert"
    assert feat.category is FeatCategory.ORIGIN
    assert feat.activities == []
    assert feat.prerequisites == []  # level=null, no items, empty requirements
    assert feat.provenance.srd_version == frozenset({"5.2"})


def test_translates_general_feat_with_prerequisite() -> None:
    feat = _translate("general-feats", "grappler.yml")
    assert feat.slug == "grappler"
    assert feat.category is FeatCategory.GENERAL
    assert len(feat.prerequisites) == 1
    assert feat.prerequisites[0].level == 4
    assert feat.prerequisites[0].requirement == "Strength or Dexterity 13+"
    assert feat.activities == []


def test_translates_fighting_style_feat() -> None:
    feat = _translate("fighting-style-feats", "archery.yml")
    assert feat.slug == "archery"
    assert feat.category is FeatCategory.FIGHTING_STYLE
    # prerequisites.items carries the fighting-style feature requirement.
    assert feat.prerequisites[0].feats == ["fighting-style"]
    assert feat.prerequisites[0].level is None


def test_translates_ability_score_improvement_empty_subtype() -> None:
    # ASI ships with an EMPTY system.type.subtype in the 2024 Foundry pack; the
    # translator falls back to GENERAL (the 5e-bits oracle classifies it so).
    feat = _translate("general-feats", "ability-score-improvement.yml")
    assert feat.slug == "ability-score-improvement"
    assert feat.category is FeatCategory.GENERAL


def test_translates_epic_boon_with_activity() -> None:
    feat = _translate("epic-boon-feats", "boon-of-fate.yml")
    assert feat.slug == "boon-of-fate"
    assert feat.category is FeatCategory.EPIC_BOON
    assert len(feat.activities) == 1
    activity = feat.activities[0]
    assert isinstance(activity, UtilityActivity)
    assert activity.kind == "utility"
    assert activity.name == "Improve Fate"
    assert activity.roll.formula == "2d4"
