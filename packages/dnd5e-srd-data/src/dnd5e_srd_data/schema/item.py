"""Item subclass schema — Item / Weapon / Armor / MagicItem."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import (
    BaseModel,
    Field,
    NonNegativeFloat,
    NonNegativeInt,
    PositiveInt,
    field_serializer,
)

from dnd5e_srd_data.schema.common import (
    Activity,
    DamagePart,
    PassiveEffect,
    Provenance,
    Range,
    ReviewState,
)


class ItemRarity(StrEnum):
    COMMON = "common"
    UNCOMMON = "uncommon"
    RARE = "rare"
    VERY_RARE = "very_rare"
    LEGENDARY = "legendary"
    ARTIFACT = "artifact"


class WeaponProperty(StrEnum):
    AMMUNITION = "ammunition"
    FINESSE = "finesse"
    HEAVY = "heavy"
    LIGHT = "light"
    LOADING = "loading"
    RANGE = "range"
    REACH = "reach"
    SPECIAL = "special"
    THROWN = "thrown"
    TWO_HANDED = "two_handed"
    VERSATILE = "versatile"


class ArmorCategory(StrEnum):
    LIGHT = "light"
    MEDIUM = "medium"
    HEAVY = "heavy"
    SHIELD = "shield"


class Item(BaseModel):
    """Base item shape. Concrete kinds (Weapon, Armor, MagicItem) extend this."""

    # Explicit discriminator so round-trip (translator → JSON → loader) preserves
    # the Item-vs-MagicItem type for entries with no structurally distinguishing
    # fields (e.g. common potions, mundane trinkets). Subclasses narrow this
    # field via Literal redefinition. See ``BundledAssetLoader.get_item``.
    item_kind: Literal["item", "weapon", "armor", "magic_item"] = "item"
    slug: str
    name: str
    description: str
    weight: NonNegativeFloat  # in pounds
    cost_gp: NonNegativeFloat | None  # None = SRD doesn't list a price (magic items)
    rarity: ItemRarity
    # Attunement metadata lives on the base because magic *weapons* (e.g.
    # Holy Avenger) and magic *armor* (e.g. Animated Shield) also require
    # attunement, not just generic MagicItem entries.
    requires_attunement: bool = False
    attunement_constraint: str | None = (
        None  # "by a paladin", "by a creature of evil alignment", etc.
    )
    provenance: Provenance
    review: ReviewState
    activities: list[Activity] = Field(default_factory=list)
    passive_effects: list[PassiveEffect] = Field(default_factory=list)
    """Foundry top-level ``effects[]`` entries preserved verbatim. Drives
    passive ActiveEffect modifiers the resolver applies while the item is
    equipped/attuned (Cloak of Protection AC+1, Ring of Protection saves+1,
    Gauntlets of Ogre Power Str=19, etc.). Empty for mundane gear."""


class Weapon(Item):
    item_kind: Literal["weapon"] = "weapon"
    weapon_category: Literal["simple_melee", "simple_ranged", "martial_melee", "martial_ranged"]
    damage_parts: list[DamagePart]
    versatile_damage: DamagePart | None = None
    range: Range
    properties: frozenset[WeaponProperty] = Field(default_factory=frozenset)
    magical_bonus: NonNegativeInt = 0
    """Foundry ``system.magicalBonus`` preserved structurally. The base
    ``damage_parts`` stay mundane (e.g. 1d8 slashing for a Longsword +3);
    consumers fold this bonus into attack and damage rolls at resolve time
    (Phase 7b engine). Zero for non-magic weapons."""
    mastery: str | None = None
    """2024 SRD weapon mastery property (Foundry ``system.mastery.value``, e.g.
    "sap", "vex", "topple"). A distinct axis from ``properties`` — never a
    ``WeaponProperty`` member. ``None`` for weapons with no mastery (all 2014
    weapons and ammunition)."""

    @field_serializer("properties")
    def _serialize_properties(self, value: frozenset[WeaponProperty]) -> list[str]:
        # frozenset → JSON list in deterministic (sorted) order so canonical
        # output is byte-stable across runs.
        return sorted(v.value for v in value)


class Armor(Item):
    item_kind: Literal["armor"] = "armor"
    armor_category: ArmorCategory
    base_ac: PositiveInt
    dex_bonus_max: NonNegativeInt | None = None  # None = uncapped (light armor)
    stealth_disadvantage: bool = False
    strength_min: NonNegativeInt | None = None
    magical_bonus: NonNegativeInt = 0
    """Foundry ``system.armor.magicalBonus`` preserved structurally. ``base_ac``
    keeps the mundane base (e.g. 18 for plate); consumers add this bonus at
    resolve time. Zero for non-magic armor."""


class MagicItem(Item):
    """Magic items that are not weapons or armor (rings, cloaks, wondrous items).

    Attunement fields are inherited from ``Item`` so magic weapons and armor
    can carry the same metadata.
    """

    item_kind: Literal["magic_item"] = "magic_item"
