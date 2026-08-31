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


def test_sacred_flame_save_ignores_cover_by_translator_allowlist():
    from dnd5e_srd_data.schema.common import SaveActivity

    spell = translate_spell_yaml(
        yaml_path=FIXTURE / "spells" / "sacred-flame.yml",
        ingest_date=date(2026, 5, 30),
        ingest_version="foundry-translator-v1",
    )
    save = next(a for a in spell.activities if isinstance(a, SaveActivity))
    assert save.save.ignore_cover is True


def test_lightning_bolt_save_keeps_cover():
    from dnd5e_srd_data.schema.common import SaveActivity

    spell = translate_spell_yaml(
        yaml_path=FIXTURE / "spells" / "lightning-bolt.yml",
        ingest_date=date(2026, 5, 30),
        ingest_version="foundry-translator-v1",
    )
    save = next(a for a in spell.activities if isinstance(a, SaveActivity))
    assert save.save.ignore_cover is False
