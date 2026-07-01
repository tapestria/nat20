from datetime import date
from pathlib import Path

from dnd5e_srd_data import CreatureSize, CreatureType, Monster
from tools.translators.foundry import translate_monster_yaml

FIXTURE = Path(__file__).parent / "fixtures" / "foundry_pack_minimal"


def test_translates_goblin():
    m = translate_monster_yaml(
        yaml_path=FIXTURE / "monsters" / "goblin.yml",
        ingest_date=date(2026, 5, 30),
        ingest_version="foundry-translator-v1",
    )
    assert isinstance(m, Monster)
    assert m.slug == "goblin"
    assert m.creature_type == CreatureType.HUMANOID
    assert m.creature_size == CreatureSize.SMALL
    assert m.ac == 15
    assert m.hp == 7
    assert m.hp_dice == "2d6"
    assert m.ability_scores.str == 8
    assert m.ability_scores.dex == 14
    assert m.movement.walk == 30
    assert m.senses.darkvision == 60
    assert m.cr == 0.25
    assert m.proficiency_bonus == 2
