"""Resolved grant references shared by Class/Subclass/Species."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

GrantRefType = Literal["feature", "feat", "spell", "equipment"]
"""feature=canonical/features/; feat=feats24-backed choice option (canonical/feats/);
spell=canonical/spells/; equipment=canonical/items/. 'feat' is distinct from 'feature'
so the ref stays typed-honest (separate canonical owners)."""


class GrantRef(BaseModel, frozen=True):
    ref_type: GrantRefType
    slug: str
    level: int = 0
    optional: bool = False


class ChoiceLevel(BaseModel, frozen=True):
    """One entry in an ItemChoice's per-level pick schedule: at ``level`` the
    player makes ``count`` new selections; ``replacement`` permits swapping a
    prior pick. Foundry stores ``count: null`` for replace-only levels — we
    normalize that to ``count=0`` so the schedule stays an honest pick count."""

    level: int
    count: int = 1
    replacement: bool = False


class FeatureChoice(BaseModel, frozen=True):
    """An ItemChoice advancement: a pool of options + the per-level pick
    schedule. Data-available only; selections are NOT auto-applied in this
    phase."""

    restriction_subtype: str = ""
    pool: tuple[GrantRef, ...] = Field(default_factory=tuple)
    schedule: tuple[ChoiceLevel, ...] = Field(default_factory=tuple)
