"""Shared request models + small helpers used by both ``app.py`` and
``routes_combat.py``.

Split out so the two route modules can import the same party-member wire
shape (``PartyValidateRequest``) without creating an import cycle between
them.
"""

from __future__ import annotations

import re
import secrets

from pydantic import BaseModel, Field

_SLUG_RE = re.compile(r"[^a-z0-9]+")

# Short-form -> canonical ability name. `resolve_check`'s underlying skill /
# ability / saving-throw resolvers key `ability_scores` (and match
# `proficient_saves` / the derived-from-skill ability) by the long form, so
# any abbreviated input from a route body is normalized before it reaches
# the engine.
ABILITY_ALIASES = {
    "str": "strength",
    "dex": "dexterity",
    "con": "constitution",
    "int": "intelligence",
    "wis": "wisdom",
    "cha": "charisma",
}


def slugify(name: str) -> str:
    return _SLUG_RE.sub("-", name.strip().lower()).strip("-")


def full_ability(name: str) -> str:
    lowered = name.strip().lower()
    return ABILITY_ALIASES.get(lowered, lowered)


def resolve_seed(seed: int | None) -> int:
    return seed if seed is not None else secrets.randbits(32)


class AbilityScoresModel(BaseModel):
    str_: int = Field(default=10, alias="str")
    dex: int = 10
    con: int = 10
    int_: int = Field(default=10, alias="int")
    wis: int = 10
    cha: int = 10

    model_config = {"populate_by_name": True}


class BuildRequest(BaseModel):
    species_slug: str
    class_slug: str
    subclass_slug: str | None = None
    level: int = 1
    ability_scores: AbilityScoresModel = Field(default_factory=lambda: AbilityScoresModel())
    equipment: tuple[str, ...] = ()


class PartyValidateRequest(BaseModel):
    name: str
    entity_id: str | None = None
    build: BuildRequest
    spells_known: list[str] | None = None
    hp_current: int | None = None


__all__ = [
    "ABILITY_ALIASES",
    "AbilityScoresModel",
    "BuildRequest",
    "PartyValidateRequest",
    "full_ability",
    "resolve_seed",
    "slugify",
]
