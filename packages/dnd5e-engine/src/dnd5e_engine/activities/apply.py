"""Damage application for the Activity resolver — partition by type, apply
target-side vulnerability / resistance / immunity, emit ``DamageApplied``.

MIRRORS, does not import from, ``effects/damage.py``:

* Apply order is vulnerability ×2 → resistance //2 (integer floor) → immunity ⇒ 0,
  matching ``_apply_resistance`` (Avrae's ``do_resistances`` order). An ``"all"``
  wildcard is honored in each list (SRD §Conditions/Petrified emits "all").
* ``is_overkill`` mirrors ``effects/damage.py:192`` — ``final_amount >
  target.hp_current`` (strictly greater).
* The ``DamageApplied`` event is emitted UNCONDITIONALLY after applying
  modifiers, exactly as ``effects/damage.py`` does: an immune type yields
  ``DamageApplied(amount=0)``, never a suppressed event.

Modifier sources differ from the effects path. ``effects/damage.py`` reads only
the sidecar (``_read_passive_modifiers``); the Activity resolver MERGES the
static ``Combatant`` lists (``damage_resistances`` / ``damage_immunities``) with
the sidecar lists at ``ctx.passive_damage_modifiers[entity_id]``. Vulnerabilities
have no static field on ``Combatant`` and come ONLY from the sidecar.

Unknown damage types (outside the SRD 13-type set) are logged with the
``damage_type_invalid`` marker and skipped — the rolled dict is keyed by free
strings supplied upstream, so an unrecognized key must be loud-but-non-fatal,
not silently dropped (and not raised: a single bad key must not abort the whole
multi-type application).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Final, cast, get_args

from dnd5e_engine.events import DamageApplied, DamageType

if TYPE_CHECKING:
    from dnd5e_engine.activities.context import ActivityResolutionContext
    from dnd5e_engine.types.combat import Combatant

_LOGGER = logging.getLogger(__name__)

# SRD 5.1 §Damage Types — the closed 13-type set, sourced from the DamageType
# Literal so the two never drift. Mirrors ``effects/damage.py:120``.
_SRD_DAMAGE_TYPES: Final[frozenset[str]] = frozenset(get_args(DamageType))


def apply_damage(
    target: Combatant,
    rolled_by_type: dict[str, int],
    ctx: ActivityResolutionContext,
) -> None:
    """Apply a per-damage-type rolled amount to ``target`` and emit one
    ``DamageApplied`` per valid type.

    For each ``(damage_type, amount)``: validate the type against the SRD set
    (skip + log ``damage_type_invalid`` on miss), merge the static ``Combatant``
    resist/immune lists with the sidecar resist/immune/vuln lists, apply
    vuln→resist→immune, compute ``is_overkill``, and emit ``DamageApplied``.
    """
    sidecar = ctx.passive_damage_modifiers.get(target.entity_id, {})
    resistances = set(target.damage_resistances) | set(sidecar.get("resistances", ()))
    immunities = set(target.damage_immunities) | set(sidecar.get("immunities", ()))
    vulnerabilities = set(sidecar.get("vulnerabilities", ()))

    for damage_type_str, amount in rolled_by_type.items():
        if damage_type_str not in _SRD_DAMAGE_TYPES:
            _LOGGER.warning(
                "damage_type_invalid damage_type=%s target_id=%s",
                damage_type_str,
                target.entity_id,
            )
            continue
        srd_type = cast(DamageType, damage_type_str)
        final_amount = _apply_modifiers(amount, srd_type, resistances, immunities, vulnerabilities)
        ctx.event_emitter(
            DamageApplied(
                target_id=target.entity_id,
                amount=final_amount,
                damage_type=srd_type,
                is_overkill=final_amount > target.hp_current,
            )
        )


def _apply_modifiers(
    amount: int,
    damage_type: DamageType,
    resistances: set[str],
    immunities: set[str],
    vulnerabilities: set[str],
) -> int:
    """Apply vuln (×2) → resist (//2 floor) → immune (⇒0) in Avrae order.

    Mirrors ``effects/damage.py:_apply_resistance``. The ``"all"`` wildcard is
    honored in each list (SRD §Conditions/Petrified resistance-to-all).
    """
    if damage_type in vulnerabilities or "all" in vulnerabilities:
        amount *= 2
    if damage_type in resistances or "all" in resistances:
        amount //= 2
    if damage_type in immunities or "all" in immunities:
        amount = 0
    return amount
