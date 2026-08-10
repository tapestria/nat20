from datetime import date

import pytest
from pydantic import ValidationError

from dnd5e_srd_data.schema.common import (
    AttackActivity,
    AttackBlock,
    AttackDamageBlock,
    AttackTypeBlock,
    DamagePart,
    DamagePartBlock,
    Provenance,
    Range,
    ReviewState,
)
from dnd5e_srd_data.schema.item import (
    Armor,
    ArmorCategory,
    Item,
    ItemRarity,
    MagicItem,
    Weapon,
    WeaponProperty,
)


def _provenance() -> Provenance:
    return Provenance(
        source="foundry",
        source_url="x",
        ingest_date=date(2026, 5, 30),
        ingest_version="v1",
        srd_version=frozenset({"5.1"}),
    )


def test_item_base_minimal():
    item = Item(
        slug="thieves-tools",
        name="Thieves' Tools",
        description="A set of tools.",
        weight=1.0,
        cost_gp=25,
        rarity=ItemRarity.COMMON,
        provenance=_provenance(),
        review=ReviewState(),
    )
    assert item.slug == "thieves-tools"


def test_weapon_subclass_carries_damage_and_properties():
    w = Weapon(
        slug="longsword",
        name="Longsword",
        description="A versatile blade.",
        weight=3.0,
        cost_gp=15,
        rarity=ItemRarity.COMMON,
        provenance=_provenance(),
        review=ReviewState(),
        damage_parts=[DamagePart(dice="1d8", damage_type="slashing")],
        versatile_damage=DamagePart(dice="1d10", damage_type="slashing"),
        properties=frozenset({WeaponProperty.VERSATILE}),
        weapon_category="martial_melee",
        range=Range(kind="melee"),
        activities=[
            AttackActivity(
                attack=AttackBlock(
                    ability="str",
                    type=AttackTypeBlock(value="melee", classification="weapon"),
                ),
                damage=AttackDamageBlock(
                    parts=[DamagePartBlock(number=1, denomination=8, types=["slashing"])],
                ),
            ),
        ],
    )
    assert w.weapon_category == "martial_melee"
    assert WeaponProperty.VERSATILE in w.properties


def test_armor_subclass_carries_ac_and_category():
    a = Armor(
        slug="chain-shirt",
        name="Chain Shirt",
        description="Medium chain.",
        weight=20.0,
        cost_gp=50,
        rarity=ItemRarity.COMMON,
        provenance=_provenance(),
        review=ReviewState(),
        armor_category=ArmorCategory.MEDIUM,
        base_ac=13,
        dex_bonus_max=2,
        stealth_disadvantage=False,
    )
    assert a.base_ac == 13
    assert a.armor_category == ArmorCategory.MEDIUM


def test_magic_item_attunement_and_rarity():
    m = MagicItem(
        slug="cloak-of-protection",
        name="Cloak of Protection",
        description="+1 AC and saves.",
        weight=1.0,
        cost_gp=None,  # magic items have no cost in SRD
        rarity=ItemRarity.UNCOMMON,
        provenance=_provenance(),
        review=ReviewState(),
        requires_attunement=True,
    )
    assert m.requires_attunement is True
    assert m.rarity == ItemRarity.UNCOMMON


def test_weapon_mastery_optional_and_serialized():
    w = Weapon(
        slug="shortsword",
        name="Shortsword",
        description="A light blade.",
        weight=2.0,
        cost_gp=10,
        rarity=ItemRarity.COMMON,
        provenance=_provenance(),
        review=ReviewState(),
        damage_parts=[DamagePart(dice="1d6", damage_type="piercing")],
        properties=frozenset({WeaponProperty.FINESSE, WeaponProperty.LIGHT}),
        weapon_category="martial_melee",
        range=Range(kind="melee"),
        mastery="sap",
    )
    assert w.mastery == "sap"
    assert w.model_dump(mode="json")["mastery"] == "sap"


def test_weapon_mastery_defaults_none():
    w = Weapon(
        slug="club",
        name="Club",
        description="A simple cudgel.",
        weight=2.0,
        cost_gp=1,
        rarity=ItemRarity.COMMON,
        provenance=_provenance(),
        review=ReviewState(),
        damage_parts=[DamagePart(dice="1d4", damage_type="bludgeoning")],
        properties=frozenset({WeaponProperty.LIGHT}),
        weapon_category="simple_melee",
        range=Range(kind="melee"),
    )
    assert w.mastery is None
    assert w.model_dump(mode="json")["mastery"] is None


def test_item_uses_carries_charges_and_recovery():
    from dnd5e_srd_data.schema.feature import RecoveryRule
    from dnd5e_srd_data.schema.item import ItemUses

    uses = ItemUses(
        max="7",
        recovery=[RecoveryRule(period="dawn", type="formula", formula="1d6 + 1")],
    )
    item = Item(
        slug="wand-of-lightning-bolts",
        name="Wand of Lightning Bolts",
        description="d",
        weight=0.0,
        cost_gp=None,
        rarity="rare",
        provenance=_provenance(),
        review=ReviewState(),
        uses=uses,
    )
    assert item.uses is not None
    assert item.uses.max == "7"
    assert item.uses.spent == 0
    assert item.uses.auto_destroy is False
    assert item.uses.recovery[0].period == "dawn"
    assert item.uses.recovery[0].formula == "1d6 + 1"


def test_item_uses_defaults_none_and_serializes():
    item = Item(
        slug="rope",
        name="Rope",
        description="d",
        weight=5.0,
        cost_gp=1.0,
        rarity="common",
        provenance=_provenance(),
        review=ReviewState(),
    )
    assert item.uses is None
    assert item.model_dump(mode="json")["uses"] is None


def test_item_rarity_default_when_unknown():
    """rarity is required at schema level — null upstream must be resolved by translator,
    not silently defaulted to COMMON here."""
    with pytest.raises(ValidationError):
        Item(
            slug="x",
            name="x",
            description="x",
            weight=0,
            cost_gp=0,
            # rarity missing — must be ValidationError, not silent default
            provenance=_provenance(),
            review=ReviewState(),
        )
