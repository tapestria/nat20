from datetime import date
from pathlib import Path

import pytest

from tools.translators.foundry import translate_species_yaml

PACKS = Path("raw_sources/foundry/packs/_source")
INGEST = dict(ingest_date=date(2026, 6, 4), ingest_version="foundry-translator-v1")
pytestmark = pytest.mark.skipif(not PACKS.is_dir(), reason="raw_sources/foundry not populated")


def test_dwarf_surfaces_poison_resistance_trait_grant():
    sp = translate_species_yaml(PACKS / "origins24/species/dwarf.yml", **INGEST)
    assert "dr:poison" in sp.trait_grants
