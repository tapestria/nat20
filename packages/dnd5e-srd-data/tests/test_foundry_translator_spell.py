"""Foundry spell yml → canonical Spell: uuid emission."""

from datetime import date
from pathlib import Path

from tools.translators.foundry import translate_spell_yaml

FIXTURE = Path(__file__).parent / "fixtures" / "foundry_pack_minimal"


def test_spell_carries_full_compendium_uuid():
    spell = translate_spell_yaml(
        yaml_path=FIXTURE / "spells" / "lightning-bolt.yml",
        ingest_date=date(2026, 5, 30),
        ingest_version="foundry-translator-v1",
    )
    assert spell.slug == "lightning-bolt"
    assert spell.foundry_uuid == "Compendium.dnd5e.spells24.Item.phbsplLightningB"
