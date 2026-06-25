"""Feat schema (2024 SRD).

Foundry encodes the 17 2024 SRD feats as ``type: feat`` documents split across
four ``feats24/`` subdirs. The feat *category* lives in ``system.type.subtype``
(``origin`` / ``general`` / ``fightingStyle`` / ``epicBoon``) — the translator
maps those Foundry codes onto :class:`FeatCategory`. Most feats are passive
benefit grants with an empty ``system.activities``; the four epic boons that
grant an actionable ability (Boon of Fate, Spell Recall, Dimensional Travel,
the Night Spirit) carry real ``system.activities`` in the same shape spells and
weapons use, so :class:`Feat` reuses the :data:`Activity` discriminated union.

Foundry's ``system.prerequisites`` block carries a minimum character ``level``
and an ``items`` list of prerequisite-feature identifiers (the Fighting Style
feats require the ``fighting-style`` feature); ``system.requirements`` is the
human-readable prerequisite prose (e.g. "Strength or Dexterity 13+"). Both are
folded into :class:`FeatPrerequisite`.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from dnd5e_srd_data.schema.common import Activity, Provenance, ReviewState


class FeatCategory(StrEnum):
    """The four 2024 SRD feat categories. Maps from Foundry's
    ``system.type.subtype`` (note the camelCase Foundry codes ``fightingStyle``
    / ``epicBoon`` translate to the snake-case members here)."""

    ORIGIN = "origin"
    GENERAL = "general"
    FIGHTING_STYLE = "fighting_style"
    EPIC_BOON = "epic_boon"


class FeatPrerequisite(BaseModel, frozen=True):
    """A feat's prerequisite. ``level`` is the minimum character level (``None``
    when unconstrained), ``feats`` lists prerequisite feature/feat identifiers
    from Foundry's ``system.prerequisites.items``, and ``requirement`` carries
    the free-text prose from ``system.requirements``."""

    level: int | None = None
    feats: list[str] = Field(default_factory=list)
    requirement: str = ""


class Feat(BaseModel):
    slug: str
    name: str
    description: str
    category: FeatCategory
    prerequisites: list[FeatPrerequisite] = Field(default_factory=list)
    activities: list[Activity] = Field(default_factory=list)
    """Translated ``system.activities`` (reusing the shared :data:`Activity`
    discriminated union). Empty for the 13 passive feats; populated for the
    four epic boons that grant an actionable ability."""
    provenance: Provenance
    review: ReviewState

    entry_kind: Literal["feat"] = "feat"
