"""Canonical Feature model: a class/subclass/species feature document."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from dnd5e_srd_data.schema.advancement import AdvancementEntry
from dnd5e_srd_data.schema.common import Activity, PassiveEffect, Provenance, ReviewState

FeatureType = Literal["class_feature", "subclass_feature", "species_trait"]


class Feature(BaseModel):
    slug: str
    name: str
    description: str = ""
    feature_type: FeatureType
    foundry_id: str = ""
    source_slug: str = ""
    activities: list[Activity] = Field(default_factory=list)
    passive_effects: list[PassiveEffect] = Field(default_factory=list)
    # A feature's OWN ScaleValue advancement table (e.g. Channel Divinity's
    # Divine Spark die count, keyed by Cleric level) — distinct from the
    # granting class/subclass/species' advancement. Mirrors ``Class`` /
    # ``Subclass`` / ``Species``'s existing ``advancement`` field (same
    # ``AdvancementEntry`` shape); resolves feature-owned ``@scale.<feature-
    # slug>.<key>`` tokens (``activities/scale.py::build_scale_values``).
    advancement: list[AdvancementEntry] = Field(default_factory=list)
    provenance: Provenance
    review: ReviewState = Field(default_factory=ReviewState)

    entry_kind: Literal["feature"] = "feature"
