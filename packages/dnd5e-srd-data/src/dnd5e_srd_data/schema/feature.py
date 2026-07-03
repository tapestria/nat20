"""Canonical Feature model: a class/subclass/species feature document."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from dnd5e_srd_data.schema.advancement import AdvancementEntry
from dnd5e_srd_data.schema.common import Activity, PassiveEffect, Provenance, ReviewState

FeatureType = Literal["class_feature", "subclass_feature", "species_trait"]

# SRD 5.2 rest / recharge periods a limited-use feature recovers on. Foundry's
# ``uses.recovery[].period`` vocabulary observed across the SRD feature corpus;
# typed (closed set) per the typed-semantics rule.
RecoveryPeriod = Literal["sr", "lr", "day", "recharge", "initiative"]
# ``uses.recovery[].type`` — how a recovery entry refills the pool.
RecoveryType = Literal["recoverAll", "formula"]


class RecoveryRule(BaseModel):
    """One ``uses.recovery[]`` entry: on ``period``, refill by ``type``.

    ``recoverAll`` restores the pool to ``max``; ``formula`` regains
    ``formula``-many uses (e.g. Second Wind's Short-Rest ``formula: "1"``).
    """

    period: RecoveryPeriod = "lr"
    type: RecoveryType = "recoverAll"
    formula: str = ""


class FeatureUses(BaseModel):
    """A feature's top-level limited-use cap (Foundry ``shared/uses-field.mjs``).

    ``max`` is Foundry's raw expression (a bare integer like ``"1"`` or a roll-data
    token like ``"@scale.fighter.second-wind"`` / ``"@prof"``); the engine parses a
    literal integer where it can and otherwise applies a conservative floor of 1.
    ``spent`` is the seed spend (always 0 in canonical). ``recovery`` lists the rests
    that recharge it. Distinct from the activity-level ``UsesBlock`` on
    ``common.py`` — this is the feature document's OWN cap (Second Wind's rest-
    recharged use pool), mirroring how ``Feature.advancement`` mirrors the class-level
    advancement field.
    """

    max: str = ""
    spent: int = 0
    recovery: list[RecoveryRule] = Field(default_factory=list)


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
    # A feature's OWN limited-use cap (Second Wind's rest-recharged pool), carried
    # from Foundry's top-level ``system.uses``. ``None`` when the source feature has
    # no meaningful cap (no ``max`` and no ``recovery``). Mirrors the ``advancement``
    # precedent: additive, populated by the translator, byte-stable regen.
    uses: FeatureUses | None = None
    provenance: Provenance
    review: ReviewState = Field(default_factory=ReviewState)

    entry_kind: Literal["feature"] = "feature"
