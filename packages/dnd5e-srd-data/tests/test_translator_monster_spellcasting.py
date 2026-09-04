from datetime import date
from pathlib import Path

from dnd5e_srd_data import Monster
from tools.translators.foundry import translate_monster_yaml

FIXTURE = Path(__file__).parent / "fixtures" / "foundry_pack_minimal"


def test_translator_reads_attributes_spellcasting():
    m = translate_monster_yaml(
        yaml_path=FIXTURE / "monsters" / "mage-lite.yml",
        ingest_date=date(2026, 5, 30),
        ingest_version="foundry-translator-v1",
    )
    assert isinstance(m, Monster)
    assert m.spellcasting_ability == "int"


def test_translator_defaults_spellcasting_ability_to_none():
    m = translate_monster_yaml(
        yaml_path=FIXTURE / "monsters" / "goblin.yml",
        ingest_date=date(2026, 5, 30),
        ingest_version="foundry-translator-v1",
    )
    assert m.spellcasting_ability is None
