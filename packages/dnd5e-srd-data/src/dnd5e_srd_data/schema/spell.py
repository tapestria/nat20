"""Spell schema — surface fields only.

Foundry's ``system.activities`` deep tree is preserved structurally via the
shared :class:`Activity` model (matches the items deferral in PR 1); the
Phase 7b resolver will walk it. Phase 7a captures every surface field the
seeder needs (level, school, components, casting time, range, duration,
materials) plus the verbatim activity tree.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, NonNegativeInt, field_serializer

from dnd5e_srd_data.schema.common import (
    Activity,
    PassiveEffect,
    Provenance,
    ReviewState,
)


class SpellSchool(StrEnum):
    """Foundry's 3-letter codes. The translator preserves the upstream value
    verbatim; ``trs`` (Transmutation) is Foundry's choice over the more common
    ``tra`` and is kept for round-trip fidelity.
    """

    ABJURATION = "abj"
    CONJURATION = "con"
    DIVINATION = "div"
    ENCHANTMENT = "enc"
    EVOCATION = "evo"
    ILLUSION = "ill"
    NECROMANCY = "nec"
    TRANSMUTATION = "trs"


class SpellComponent(StrEnum):
    VOCAL = "V"
    SOMATIC = "S"
    MATERIAL = "M"


class CastingTimeUnit(StrEnum):
    """Foundry ``system.activation.type``. ``minute``/``hour`` cover ritual-style
    long casts; ``special`` covers triggered spells (e.g. counterspell)."""

    ACTION = "action"
    BONUS = "bonus"
    REACTION = "reaction"
    MINUTE = "minute"
    HOUR = "hour"
    SPECIAL = "special"


class CastingTime(BaseModel, frozen=True):
    unit: CastingTimeUnit
    value: NonNegativeInt = 1
    condition: str = ""


class SpellRangeUnits(StrEnum):
    """Foundry ``system.range.units``. Broader than weapon ``Range`` (which
    only covers feet/miles) because spells include ``self``/``touch``/``spec``."""

    SELF = "self"
    TOUCH = "touch"
    FEET = "ft"
    MILES = "mi"
    ANY = "any"
    SPECIAL = "spec"


class SpellRange(BaseModel, frozen=True):
    units: SpellRangeUnits
    value: NonNegativeInt | None = None
    special: str | None = None


class SpellDurationUnits(StrEnum):
    """Foundry ``system.duration.units``. Includes Foundry's specific
    indefinite-duration codes (``disp`` = until dispelled, ``dstr`` =
    until destroyed) that the 2014 SRD pack ships on permanency-style
    spells (continual flame, magic mouth, glyph of warding, symbol)."""

    INSTANT = "inst"
    ROUND = "round"
    MINUTE = "minute"
    HOUR = "hour"
    DAY = "day"
    UNTIL_DISPELLED = "disp"
    UNTIL_DESTROYED = "dstr"
    PERMANENT = "perm"
    SPECIAL = "spec"


class SpellDuration(BaseModel, frozen=True):
    units: SpellDurationUnits
    value: NonNegativeInt | None = None


class SpellMaterials(BaseModel, frozen=True):
    """Material-component description. ``cost`` is in gold pieces (Foundry
    ships an int); ``consumed`` flags ones that vanish on cast (e.g. diamond
    dust for raise dead)."""

    value: str = ""
    consumed: bool = False
    cost: NonNegativeInt = 0
    supply: NonNegativeInt = 0


class SpellPreparation(BaseModel, frozen=True):
    """Class-list metadata. ``mode`` is Foundry's enum (prepared/innate/atwill/
    pact/...); ``prepared`` reflects character-sheet state (false for templates)."""

    mode: str = ""
    prepared: bool = False


class Spell(BaseModel):
    """One canonical spell entry. Slug matches the Foundry filename stem.

    The class list (which classes can cast the spell) is derived by the
    seeder from class advancement entries; the spell document itself doesn't
    ship that list in Foundry's 2014 pack.
    """

    slug: str
    name: str
    description: str
    level: NonNegativeInt  # 0 = cantrip
    school: SpellSchool
    components: frozenset[SpellComponent] = Field(default_factory=frozenset)
    ritual: bool = False
    concentration: bool = False
    casting_time: CastingTime
    range: SpellRange
    duration: SpellDuration
    materials: SpellMaterials = Field(default_factory=SpellMaterials)
    preparation: SpellPreparation = Field(default_factory=SpellPreparation)
    activities: list[Activity] = Field(default_factory=list)
    """Foundry's ``system.activities`` deep tree, preserved structurally.
    The Phase 7b resolver walks these; Phase 7a only persists them."""
    passive_effects: list[PassiveEffect] = Field(default_factory=list)
    """Top-level Foundry ``effects[]`` entries — currently empty for SRD
    spells but preserved structurally so future packs round-trip."""
    provenance: Provenance
    review: ReviewState

    # Explicit discriminator for symmetry with Item/MagicItem; spells live in
    # their own oracle so this stays singular.
    entry_kind: Literal["spell"] = "spell"

    @field_serializer("components")
    def _serialize_components(self, value: frozenset[SpellComponent]) -> list[str]:
        # frozenset iteration order is non-deterministic across processes
        # (PYTHONHASHSEED). Sort so the regen-clean gate (PR A task A7) is
        # stable run-over-run. Same pattern as Provenance.srd_version /
        # Class.saving_throws / Weapon.properties.
        return sorted(value)
