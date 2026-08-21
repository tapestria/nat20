"""forge_item — compact weapon recipes → schema-valid, round-trippable raw dicts.

Takes a canonical weapon base slug plus a small set of overrides (name,
magical bonus, one extra damage part) and produces a raw dict shaped exactly
like the ones :class:`~nat20_bridge.homebrew.HomebrewStore` persists — i.e.
``json.loads(Weapon.model_dump_json())`` — so callers can hand the result
straight to ``HomebrewStore.add("items", raw)``.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from dnd5e_srd_data.schema.common import DamagePart

if TYPE_CHECKING:
    from dnd5e_srd_data.loader import AssetLoader

_EXTRA_DAMAGE_RE = re.compile(r"^(\d+d\d+(?:[+-]\d+)?):([a-z]+)$")

_HB_PREFIX = "hb-"


class ForgeError(Exception):
    """Raised when a forge recipe is invalid (unknown base, malformed damage, ...)."""


def _slugify(name: str) -> str:
    return f"{_HB_PREFIX}{name.strip().lower().replace(' ', '-')}"


def _parse_extra_damage(extra_damage: str) -> DamagePart:
    match = _EXTRA_DAMAGE_RE.match(extra_damage)
    if match is None:
        raise ForgeError(
            f"malformed extra_damage {extra_damage!r}; expected format 'NdM[+/-B]:type'"
        )
    dice, damage_type = match.groups()
    return DamagePart(dice=dice, damage_type=damage_type)


def forge_item(
    *,
    name: str,
    base: str,
    loader: AssetLoader,
    bonus: int = 0,
    extra_damage: str | None = None,
) -> dict[str, Any]:
    """Build a raw, schema-valid weapon dict from a canonical base weapon.

    Raises:
        ForgeError: ``base`` is not a known weapon slug, or ``extra_damage``
            doesn't match the ``"NdM[+/-B]:type"`` format.
    """
    weapon = loader.get_weapon(base)
    if weapon is None:
        raise ForgeError(f"unknown weapon base slug {base!r}")

    damage_parts = list(weapon.damage_parts)
    if extra_damage is not None:
        damage_parts.append(_parse_extra_damage(extra_damage))

    slug = _slugify(name)
    new_weapon = weapon.model_copy(
        update={
            "slug": slug,
            "name": name,
            "magical_bonus": weapon.magical_bonus + bonus,
            "damage_parts": damage_parts,
        }
    )
    dumped: dict[str, Any] = json.loads(new_weapon.model_dump_json())
    return dumped
