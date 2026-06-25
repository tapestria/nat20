from pathlib import Path

import pytest

from dnd5e_srd_data.loader import BundledAssetLoader, MemoryAssetLoader
from dnd5e_srd_data.schema.feature import Feature

_PROV = {
    "source": "foundry",
    "source_url": "x",
    "srd_version": ["5.2"],
    "ingest_date": "2026-06-04",
    "ingest_version": "x",
}


def _feature(slug: str) -> Feature:
    return Feature.model_validate(
        {
            "slug": slug,
            "name": slug,
            "feature_type": "class_feature",
            "provenance": _PROV,
            "review": {},
        }
    )


def test_memory_loader_get_feature_roundtrip():
    loader = MemoryAssetLoader(features=[_feature("rage")])
    assert loader.get_feature("rage").slug == "rage"
    assert loader.get_feature("missing") is None
    assert "rage" in loader.list_slugs("features")


@pytest.mark.skipif(
    not Path("src/dnd5e_srd_data/canonical/features").is_dir(),
    reason="run make regen first",
)
def test_bundled_loader_ships_and_loads_real_feature():
    loader = BundledAssetLoader()
    slugs = loader.list_slugs("features")
    assert slugs
    assert loader.get_feature(sorted(slugs)[0]) is not None
