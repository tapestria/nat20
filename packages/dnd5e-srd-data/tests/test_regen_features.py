import json
from pathlib import Path

import pytest

CANON = Path("src/dnd5e_srd_data/canonical")
pytestmark = pytest.mark.skipif(
    not (CANON / "features").is_dir(),
    reason="run `make regen` (needs raw_sources) before this test",
)


def test_canonical_features_populated():
    feats = list((CANON / "features").glob("*.json"))
    assert len(feats) >= 250
    rage = json.loads((CANON / "features" / "rage.json").read_text())
    assert rage["feature_type"] == "class_feature"


def test_barbarian_class_has_resolved_granted_features():
    barb = json.loads((CANON / "classes" / "barbarian.json").read_text())
    refs = barb["granted_features"]
    slugs = {g["slug"] for g in refs}
    assert "rage" in slugs
    rage_ref = next(g for g in refs if g["slug"] == "rage")
    assert rage_ref["level"] == 1
    assert rage_ref["ref_type"] == "feature"


def test_dwarf_species_has_resolved_features_and_trait_grants():
    dwarf = json.loads((CANON / "species" / "dwarf.json").read_text())
    assert "dwarven-resilience" in {g["slug"] for g in dwarf["granted_features"]}
    assert "dr:poison" in dwarf["trait_grants"]


def test_species_itemchoice_pool_surfaced_as_feature_choices():
    goliath = json.loads((CANON / "species" / "goliath.json").read_text())
    assert goliath["feature_choices"], "Goliath Giant Ancestry ItemChoice not surfaced"
    pool_slugs = {ref["slug"] for ch in goliath["feature_choices"] for ref in ch["pool"]}
    assert pool_slugs


def test_fighter_fighting_style_choice_carries_per_level_schedule():
    fighter = json.loads((CANON / "classes" / "fighter.json").read_text())
    style = next(
        ch for ch in fighter["feature_choices"] if ch["restriction_subtype"] == "fightingStyle"
    )
    schedule = style["schedule"]
    assert schedule, "Fighting Style ItemChoice lost its per-level schedule"
    # The pick happens at level 1 (count 1); later levels are replace-only.
    first = next(s for s in schedule if s["level"] == 1)
    assert first["count"] == 1
    # Schedule is sorted by level for deterministic output.
    assert [s["level"] for s in schedule] == sorted(s["level"] for s in schedule)
    # The four SRD fighting styles resolve; the six non-SRD ones are allowlisted.
    pool_slugs = {ref["slug"] for ref in style["pool"]}
    assert {"archery", "defense", "great-weapon-fighting", "two-weapon-fighting"} <= pool_slugs
