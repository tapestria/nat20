"""Canonical Feature model: a class/subclass/species feature document."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

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
    provenance: Provenance
    review: ReviewState = Field(default_factory=ReviewState)

    entry_kind: Literal["feature"] = "feature"
