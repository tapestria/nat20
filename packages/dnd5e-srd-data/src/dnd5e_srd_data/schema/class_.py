"""Class + Subclass schemas.

The rich part of a Foundry class doc is its ``system.advancement[]`` array,
which encodes hit-die / proficiencies (Trait) / class features (ItemGrant) /
ability score improvements / scale-value tables (rage damage, sneak attack
dice...). PR 2 preserves the array structurally — the seeder + Phase 7b
resolver decode per-type ``configuration`` from there.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, field_serializer

from dnd5e_srd_data.schema.advancement import AdvancementEntry
from dnd5e_srd_data.schema.common import Provenance, ReviewState
from dnd5e_srd_data.schema.refs import FeatureChoice, GrantRef


class HitDie(StrEnum):
    D6 = "d6"
    D8 = "d8"
    D10 = "d10"
    D12 = "d12"


class SpellcastingProgression(StrEnum):
    """Foundry ``system.spellcasting.progression``. ``none`` covers martial
    classes; ``pact`` covers warlock; ``third``/``half``/``full`` cover
    paladin/ranger/etc."""

    NONE = "none"
    THIRD = "third"
    HALF = "half"
    FULL = "full"
    PACT = "pact"
    ARTIFICER = "artificer"


class Spellcasting(BaseModel, frozen=True):
    """Foundry's per-class spellcasting block. Note: ``system.spellcasting.preparation``
    in Foundry is a spellbook-size formula (``{formula: "@abilities.int.mod + ..."}``),
    not a prep mode — and the 2014 SRD doesn't ship prep mode on the class
    document at all. Whether a class prepares (cleric/druid/paladin/wizard)
    vs knows (bard/ranger/sorcerer/warlock) is a per-character convention the
    seeder hardcodes by class identifier, not something canonical surfaces here.
    """

    ability: Literal["str", "dex", "con", "int", "wis", "cha", ""] = ""
    progression: SpellcastingProgression = SpellcastingProgression.NONE


class PrimaryAbility(BaseModel, frozen=True):
    """``system.primaryAbility``. ``all=True`` means a character needs every
    listed ability (paladin: str AND cha); ``False`` means any one suffices."""

    value: frozenset[Literal["str", "dex", "con", "int", "wis", "cha"]] = Field(
        default_factory=frozenset
    )
    all: bool = False

    @field_serializer("value")
    def _serialize_value(self, value: frozenset[str]) -> list[str]:
        # frozenset iteration order is non-deterministic across processes
        # (PYTHONHASHSEED). Sort so the regen-clean gate (PR A task A7) is
        # stable run-over-run. Same pattern as Provenance.srd_version /
        # Class.saving_throws / Weapon.properties.
        return sorted(value)


class Class(BaseModel):
    slug: str
    name: str
    description: str
    identifier: str
    """Foundry's ``system.identifier`` — usually equal to ``slug`` but kept
    separate because Foundry can reassign identifiers without renaming files."""
    hit_die: HitDie
    primary_ability: PrimaryAbility
    spellcasting: Spellcasting
    wealth: str = ""
    """Starting wealth roll (e.g. ``5d4 * 10``). Foundry ships it as a free
    string; the seeder parses if needed."""
    saving_throws: frozenset[Literal["str", "dex", "con", "int", "wis", "cha"]] = Field(
        default_factory=frozenset
    )
    """Derived from ``Trait`` advancement entries whose ``configuration.grants``
    contain ``saves:<ab>`` tokens. Every SRD class has exactly two."""
    subclass_identifiers: list[str] = Field(default_factory=list)
    """Foundry subclass-document UUIDs (or short identifiers if available)
    granted by ``Subclass``-type advancement entries' ``configuration``. The
    seeder resolves these against ``canonical/subclasses/`` to wire the
    class→subclass graph."""
    advancement: list[AdvancementEntry] = Field(default_factory=list)
    granted_features: list[GrantRef] = Field(default_factory=list)
    feature_choices: list[FeatureChoice] = Field(default_factory=list)
    provenance: Provenance
    review: ReviewState

    entry_kind: Literal["class"] = "class"

    @field_serializer("saving_throws")
    def _serialize_saving_throws(self, value: frozenset[str]) -> list[str]:
        return sorted(value)


class Subclass(BaseModel):
    slug: str
    name: str
    description: str
    identifier: str
    class_identifier: str
    """``system.classIdentifier`` — names the parent class via its identifier
    (e.g. ``fighter`` for Champion)."""
    spellcasting: Spellcasting
    advancement: list[AdvancementEntry] = Field(default_factory=list)
    granted_features: list[GrantRef] = Field(default_factory=list)
    feature_choices: list[FeatureChoice] = Field(default_factory=list)
    provenance: Provenance
    review: ReviewState

    entry_kind: Literal["subclass"] = "subclass"
