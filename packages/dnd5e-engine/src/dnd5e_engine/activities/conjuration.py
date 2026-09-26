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

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Literal

from dnd5e_srd_data.schema.common import (
    AttackActivity,
    AttackBlock,
    AttackDamageBlock,
    AttackTypeBlock,
    DamagePartBlock,
    DamageScalingBlock,
)
from dnd5e_srd_data.schema.item import Weapon

from dnd5e_engine.events import DamageType
from dnd5e_engine.types.effects import ActiveEffect

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


# Foundry item-change keys an enchantment writes onto its weapon. Magic Weapon's
# riders carry exactly these two plus a cosmetic ``name`` override.
_MAGICAL_BONUS_KEY: Final = "system.magicalBonus"
_PROPERTIES_KEY: Final = "system.properties"
_MAGICAL_PROPERTY: Final = "mgc"


def enchant_weapon(weapon: Weapon, effects: Sequence[ActiveEffect]) -> Weapon:
    """``weapon`` as the enchantments among ``effects`` make it.

    SRD 5.2 Magic Weapon: "that weapon becomes a magic weapon with a +1 bonus
    to attack rolls and damage rolls." Only an effect whose
    ``flags[ENCHANTED_WEAPON_FLAG]`` names this weapon's slug applies: an
    ``upgrade`` of ``system.magicalBonus`` raises ``magical_bonus`` to at least
    its value (a bonus never stacks with another), and an ``add`` of the
    ``mgc`` property makes the weapon magical, which also overcomes resistance
    to nonmagical damage. Every other change key (the ``name`` override) is
    ignored. Returns ``weapon`` itself when nothing applies.
    """
    bonus, magical = weapon.magical_bonus, weapon.magical
    for effect in effects:
        if effect.flags.get(ENCHANTED_WEAPON_FLAG) != weapon.slug:
            continue
        for change in effect.changes:
            if change.key == _MAGICAL_BONUS_KEY and change.mode == "upgrade":
                bonus = max(bonus, int(change.value))
            elif (
                change.key == _PROPERTIES_KEY
                and change.mode == "add"
                and change.value == _MAGICAL_PROPERTY
            ):
                magical = True
    if (bonus, magical) == (weapon.magical_bonus, weapon.magical):
        return weapon
    return weapon.model_copy(update={"magical_bonus": bonus, "magical": magical})


@dataclass(frozen=True)
class ConstructSpec:
    """A caster-owned spell construct's fixed numbers: how far it reaches and
    moves, and the damage its attack deals at the spell's base level."""

    reach_ft: int
    move_ft: int
    damage_die: int
    damage_type: DamageType
    base_level: int


# SRD 5.2 Spiritual Weapon: "you can immediately make one melee spell attack
# against one creature within 5 feet of the force. On a hit, the target takes
# Force damage equal to 1d8 plus your spellcasting ability modifier. As a Bonus
# Action on your later turns, you can move the force up to 20 feet and repeat
# the attack against a creature within 5 feet of it." The Foundry actor that
# carries this attack upstream is a quarantined CC-BY conjuration, so the
# registry holds the numbers (spec §6 D3).
CONSTRUCTS: Final[Mapping[str, ConstructSpec]] = MappingProxyType(
    {
        "spiritual-weapon": ConstructSpec(
            reach_ft=5, move_ft=20, damage_die=8, damage_type="force", base_level=2
        ),
    }
)


def construct_attack_activity(
    spec: ConstructSpec, *, slot_level: int, attack_bonus: int, damage_bonus: int
) -> AttackActivity:
    """The construct's attack as a flat melee spell attack: ``attack_bonus`` to
    hit and one damage part of ``spec.damage_die`` dice plus ``damage_bonus``.

    SRD 5.2 Spiritual Weapon: "The damage increases by 1d8 for every slot
    level above 2." The dice count carries the slot level, so the part's own
    upcast scaling is zeroed: the resolution context also carries the slot
    level (its spell level is what makes the hit magical) and would otherwise
    add the same dice again. No ``@``-token: the caller resolves both numbers.
    """
    return AttackActivity(
        id="construct-attack",
        name="Construct attack",
        attack=AttackBlock(
            bonus=str(attack_bonus),
            flat=True,
            type=AttackTypeBlock(value="melee", classification="spell"),
        ),
        damage=AttackDamageBlock(
            include_base=False,
            parts=[
                DamagePartBlock(
                    number=1 + slot_level - spec.base_level,
                    denomination=spec.damage_die,
                    bonus=str(damage_bonus),
                    types=[spec.damage_type],
                    scaling=DamageScalingBlock(number=0),
                )
            ],
        ),
    )


__all__ = [
    "CONJURATION_ALLOWLIST",
    "CONSTRUCTS",
    "ENCHANTED_WEAPON_FLAG",
    "TRANSFORM_FORM_FLAG",
    "ConjurationCarrier",
    "ConjurationKind",
    "ConstructRequest",
    "ConstructSpec",
    "TransformRequest",
    "TransformSource",
    "construct_attack_activity",
    "enchant_weapon",
]
