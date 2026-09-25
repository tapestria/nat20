"""Conjurations: the allowlisted summon, enchant and transform sources (C21).

A few SRD 5.2 spells and features resolve by making something. Spiritual Weapon
makes a construct: "You create a floating, spectral force that resembles a
weapon of your choice". Magic Weapon enchants a weapon: "that weapon becomes a
magic weapon". Wild Shape, and Polymorph on a failed save, put a creature in a
Beast's stat block: "Your game statistics are replaced by the Beast's stat
block". The dataset carries their Foundry ``summon`` / ``enchant`` /
``transform`` activities, but no model the engine can resolve generically, so
the engine keeps a typed registry keyed by source slug: a Python registry now,
a dataset field later, as conditions and traits began (spec §6 D3). Every other
summon, enchant and transform activity stays narrative.

The resolver routes an allowlisted activity only when the orchestrator hands it
a pre-validated ``ConjurationCarrier``, and reports what the orchestrator must
fold after resolution through typed requests. Pure data: no loader, no
orchestrator import, no I/O.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Literal

ConjurationKind = Literal["construct", "enchant", "transform", "transform_rider"]
TransformSource = Literal["wild-shape", "polymorph"]

# The only sources the resolver routes. Polymorph is a ``save`` activity whose
# failed save carries the transform (``"transform_rider"``), so its routing is
# the orchestrator's; the monster summon riders, the item summons, Sacred Weapon
# and the other Polymorph-family spells are absent and stay narrative.
CONJURATION_ALLOWLIST: Final[Mapping[str, ConjurationKind]] = MappingProxyType(
    {
        "spiritual-weapon": "construct",
        "magic-weapon": "enchant",
        "wild-shape": "transform",
        "polymorph": "transform_rider",
    }
)

#: ``ActiveEffect.flags`` key naming the weapon slug an enchantment rides on
#: (Magic Weapon: "You touch a nonmagical weapon"). A host may seed an
#: enchantment through ``start_combat(active_effects=)`` with it.
ENCHANTED_WEAPON_FLAG: Final = "enchanted_weapon"
#: ``ActiveEffect.flags`` key naming the Beast form a transform effect holds.
TRANSFORM_FORM_FLAG: Final = "transform_form"


@dataclass(frozen=True)
class ConjurationCarrier:
    """The orchestrator's pre-validated inputs for one resolution of an
    allowlisted source: the weapon an enchantment touches, the Beast form a
    transform takes, the cell a construct appears in. ``None`` fields leave the
    matching activity narrative."""

    source_slug: str
    weapon_slug: str | None = None
    form_slug: str | None = None
    cell: str | None = None


@dataclass(frozen=True)
class ConstructRequest:
    """A construct the orchestrator registers after resolution: its spell, its
    owner, its cell, the level it was cast at, and the creatures its immediate
    attack may target."""

    spell_id: str
    owner_id: str
    cell: str
    slot_level: int
    target_ids: tuple[str, ...]


@dataclass(frozen=True)
class TransformRequest:
    """A creature the orchestrator shape-shifts after resolution."""

    target_id: str
    form_slug: str
    source: TransformSource


__all__ = [
    "CONJURATION_ALLOWLIST",
    "ENCHANTED_WEAPON_FLAG",
    "TRANSFORM_FORM_FLAG",
    "ConjurationCarrier",
    "ConjurationKind",
    "ConstructRequest",
    "TransformRequest",
    "TransformSource",
]
