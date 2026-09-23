from datetime import date
from pathlib import Path

from dnd5e_srd_data import Monster
from tools.translators.foundry import translate_monster_yaml

FIXTURE = Path(__file__).parent / "fixtures" / "foundry_pack_minimal"


def test_translator_falls_back_to_top_level_when_cast_activity_ability_is_empty():
    """mage-lite has one cast activity with an empty ``spell.ability`` and a
    valid top-level ``attributes.spellcasting: int`` — precedence step 2."""
    m = translate_monster_yaml(
        yaml_path=FIXTURE / "monsters" / "mage-lite.yml",
        ingest_date=date(2026, 5, 30),
        ingest_version="foundry-translator-v1",
    )
    assert isinstance(m, Monster)
    assert m.spellcasting_ability == "int"


def test_translator_prefers_per_activity_ability_over_invalid_top_level():
    """ghost-lite carries the Foundry non-caster placeholder
    (``attributes.spellcasting: str``) at the top level, but its one cast
    activity's own ``spell.ability`` is ``cha`` — precedence step 1 wins."""
    m = translate_monster_yaml(
        yaml_path=FIXTURE / "monsters" / "ghost-lite.yml",
        ingest_date=date(2026, 5, 30),
        ingest_version="foundry-translator-v1",
    )
    assert isinstance(m, Monster)
    assert m.spellcasting_ability == "cha"


def test_translator_defaults_spellcasting_ability_to_none_without_cast_activity():
    """goblin has no cast activity at all, so it is never tagged even though
    it has no top-level spellcasting field either."""
    m = translate_monster_yaml(
        yaml_path=FIXTURE / "monsters" / "goblin.yml",
        ingest_date=date(2026, 5, 30),
        ingest_version="foundry-translator-v1",
    )
    assert m.spellcasting_ability is None
