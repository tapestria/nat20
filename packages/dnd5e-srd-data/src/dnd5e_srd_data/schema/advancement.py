"""Shared advancement-entry schema for Class / Subclass / Species.

Foundry's ``system.advancement`` is a tagged-union array. We preserve every
entry's surface fields (``type``, ``level``, ``title``, ``hint``, ``_id``)
structurally; ``configuration`` is kept as an opaque dict because its shape
varies per ``type`` and downstream consumers (Phase 7b resolver, Tapestria
seeder) read it directly. The Foundry ``effects[]`` tree on individual
class/subclass/race documents is not modelled here (Phase 7b territory).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, NonNegativeInt


class AdvancementType(StrEnum):
    """Foundry's advancement union tags. Order matches frequency observed in
    the upstream 2014 SRD pack so the catalog stays self-explanatory.

    See ``audit/foundry_shape_catalog.json`` for variance per tag.
    """

    ITEM_GRANT = "ItemGrant"
    TRAIT = "Trait"
    ABILITY_SCORE_IMPROVEMENT = "AbilityScoreImprovement"
    SCALE_VALUE = "ScaleValue"
    HIT_POINTS = "HitPoints"
    SUBCLASS = "Subclass"
    ITEM_CHOICE = "ItemChoice"
    SIZE = "Size"


class AdvancementEntry(BaseModel):
    """One entry in a Foundry ``system.advancement`` array.

    The structured ``configuration`` payload differs per ``type``; we keep it
    as an opaque dict so canonical preserves every byte without locking the
    library into a per-type schema before downstream consumers stabilise.
    """

    id: str = Field(alias="_id")
    type: AdvancementType
    level: NonNegativeInt = 0
    title: str = ""
    hint: str = ""
    class_restriction: str = ""
    """Foundry's ``classRestriction``. Empty string for unscoped grants, or
    ``"primary"``/``"secondary"`` to flag multi-class behavior — the rogue's
    level-1 save proficiencies carry ``primary``, while later class-feature
    grants like Slippery Mind (level-15 wis save) have no restriction."""
    configuration: dict[str, Any] = Field(default_factory=dict)
    value: dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}
