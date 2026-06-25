from pathlib import Path

import pytest

from tools.translators.foundry import build_feature_index

PACKS = Path("raw_sources/foundry/packs/_source")
pytestmark = pytest.mark.skipif(not PACKS.is_dir(), reason="raw_sources/foundry not populated")


def test_index_maps_full_uuid_to_feature_slug_via_id():
    idx = build_feature_index(PACKS)
    ref = idx["Compendium.dnd5e.classes24.Item.phbbrbRage000000"]
    assert ref.ref_type == "feature" and ref.slug == "rage"


def test_index_resolves_equipment_spell_and_feat_targets():
    idx = build_feature_index(PACKS)
    assert idx["Compendium.dnd5e.equipment24.Item.phbagAcid0000000"].ref_type == "equipment"
    assert any(r.ref_type == "spell" for r in idx.values())
    archery = idx["Compendium.dnd5e.feats24.Item.phbfstArchery000"]
    assert archery.ref_type == "feat"
