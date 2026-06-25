"""Species schema.

Foundry treats every player-pickable 2024 species (dragonborn, dwarf, the
three elf lineages, the two gnome lineages, goliath, halfling, human, orc,
the three tiefling legacies) as a leaf ``type: race`` document — the 2024 SRD
folds the old "subrace" concept into per-lineage leaf entries. Size sits in a
``Size`` advancement entry rather than a top-level field; the translator
surfaces it for convenience. The 2024 SRD removed species ability-score
bonuses (ASIs now derive from the character's background), so there is no
ability-bonus field on this model.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from dnd5e_srd_data.schema.advancement import AdvancementEntry
from dnd5e_srd_data.schema.common import (
    Movement,
    Provenance,
    ReviewState,
    Senses,
)
from dnd5e_srd_data.schema.monster import CreatureSize
from dnd5e_srd_data.schema.refs import FeatureChoice, GrantRef


class CreatureKind(StrEnum):
    """``system.type.value`` for Foundry species docs. The 2024 SRD species are
    universally ``humanoid``; the enum exists so non-SRD content can round-trip."""

    ABERRATION = "aberration"
    BEAST = "beast"
    CELESTIAL = "celestial"
    CONSTRUCT = "construct"
    DRAGON = "dragon"
    ELEMENTAL = "elemental"
    FEY = "fey"
    FIEND = "fiend"
    GIANT = "giant"
    HUMANOID = "humanoid"
    MONSTROSITY = "monstrosity"
    OOZE = "ooze"
    PLANT = "plant"
    UNDEAD = "undead"


class CreatureTypeRef(BaseModel, frozen=True):
    """Foundry ``system.type`` block: a primary kind plus open-vocab subtype."""

    value: CreatureKind
    subtype: str = ""
    custom: str = ""


class Species(BaseModel):
    slug: str
    name: str
    description: str
    creature_type: CreatureTypeRef
    size: CreatureSize
    """Surfaced from the ``Size`` advancement entry. Foundry species without a
    Size entry default to MEDIUM (matches the SRD)."""
    movement: Movement
    senses: Senses
    languages: list[str] = Field(default_factory=list)
    """Derived from ``Trait`` advancement entries with grants matching
    ``languages:standard:<name>`` / ``languages:exotic:<name>``. Order
    preserved from Foundry. Empty for the 2024 SRD species (the 2024 rules
    grant languages via the character's background, not the species)."""
    trait_grants: list[str] = Field(default_factory=list)
    """Foundry ``Trait`` advancement ``configuration.grants`` like ``"dr:poison"``
    — surfaced because the granting feature doc is often prose-only."""
    advancement: list[AdvancementEntry] = Field(default_factory=list)
    granted_features: list[GrantRef] = Field(default_factory=list)
    feature_choices: list[FeatureChoice] = Field(default_factory=list)
    provenance: Provenance
    review: ReviewState

    entry_kind: Literal["species"] = "species"
