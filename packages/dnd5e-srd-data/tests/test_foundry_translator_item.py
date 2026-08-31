from datetime import date
from pathlib import Path

from dnd5e_srd_data import (
    ArmorCategory,
    DamagePart,
    Weapon,
    WeaponProperty,
)
from tools.translators.foundry import (
    translate_armor_yaml,
    translate_generic_item_yaml,
    translate_weapon_yaml,
)

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


def test_translates_wand_charges():
    item = translate_generic_item_yaml(
        yaml_path=FIXTURE / "wands" / "wand-of-lightning-bolts.yml",
        ingest_date=date(2026, 5, 30),
        ingest_version="foundry-translator-v1",
    )
    assert item.uses is not None
    assert item.uses.max == "7"
    assert item.uses.spent == 0
    assert item.uses.auto_destroy is False
    assert len(item.uses.recovery) == 1
    assert item.uses.recovery[0].period == "dawn"
    assert item.uses.recovery[0].type == "formula"
    assert item.uses.recovery[0].formula == "1d6 + 1"


def test_longsword_has_no_uses():
    w = translate_weapon_yaml(
        yaml_path=FIXTURE / "weapons" / "longsword.yml",
        ingest_date=date(2026, 5, 30),
        ingest_version="foundry-translator-v1",
    )
    assert w.uses is None


def test_mgc_property_sets_weapon_magical_without_touching_properties():
    w = translate_weapon_yaml(
        yaml_path=FIXTURE / "weapons" / "dagger-of-venom-lite.yml",
        ingest_date=date(2026, 5, 30),
        ingest_version="foundry-translator-v1",
    )
    assert w.magical is True
    assert w.magical_bonus == 1
    assert WeaponProperty.FINESSE in w.properties
    assert "mgc" not in {p.value for p in w.properties}  # never a WeaponProperty member


def test_mundane_weapon_and_armor_are_not_magical():
    w = translate_weapon_yaml(
        yaml_path=FIXTURE / "weapons" / "longsword.yml",
        ingest_date=date(2026, 5, 30),
        ingest_version="foundry-translator-v1",
    )
    a = translate_armor_yaml(
        yaml_path=FIXTURE / "armor" / "chain-shirt.yml",
        ingest_date=date(2026, 5, 30),
        ingest_version="foundry-translator-v1",
    )
    assert w.magical is False and a.magical is False
