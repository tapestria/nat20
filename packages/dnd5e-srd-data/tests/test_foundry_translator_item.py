from datetime import date
from pathlib import Path

from dnd5e_srd_data import (
    ArmorCategory,
    DamagePart,
    Weapon,
    WeaponProperty,
)
from tools.translators.foundry import translate_armor_yaml, translate_weapon_yaml

FIXTURE = Path(__file__).parent / "fixtures" / "foundry_pack_minimal"


def test_translates_longsword():
    w = translate_weapon_yaml(
        yaml_path=FIXTURE / "weapons" / "longsword.yml",
        ingest_date=date(2026, 5, 30),
        ingest_version="foundry-translator-v1",
    )
    assert isinstance(w, Weapon)
    assert w.slug == "longsword"
    assert w.name == "Longsword"
    assert w.weapon_category == "martial_melee"
    assert w.damage_parts == [DamagePart(dice="1d8", damage_type="slashing")]
    assert w.versatile_damage == DamagePart(dice="1d10", damage_type="slashing")
    assert WeaponProperty.VERSATILE in w.properties
    assert w.range.kind == "melee"
    assert w.provenance.source == "foundry"


def test_translated_provenance_srd_version_is_5_2():
    w = translate_weapon_yaml(
        yaml_path=FIXTURE / "weapons" / "longsword.yml",
        ingest_date=date(2026, 5, 30),
        ingest_version="foundry-translator-v1",
    )
    assert w.provenance.srd_version == frozenset({"5.2"})


def test_translates_chain_shirt():
    a = translate_armor_yaml(
        yaml_path=FIXTURE / "armor" / "chain-shirt.yml",
        ingest_date=date(2026, 5, 30),
        ingest_version="foundry-translator-v1",
    )
    assert a.slug == "chain-shirt"
    assert a.armor_category == ArmorCategory.MEDIUM
    assert a.base_ac == 13
    assert a.dex_bonus_max == 2
