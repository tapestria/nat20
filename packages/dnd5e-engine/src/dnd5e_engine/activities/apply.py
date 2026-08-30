"""Damage application for the Activity resolver — partition by type, apply
target-side vulnerability / resistance / immunity, emit ``DamageApplied``.

MIRRORS, does not import from, ``effects/damage.py``:

* Apply order is vulnerability ×2 → resistance //2 (integer floor) → immunity ⇒ 0,
  matching ``_apply_resistance`` (the legacy ``do_resistances`` order). An ``"all"``
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

# C22 — the SRD Bludgeoning / Piercing / Slashing triple. A magical source
# (``Weapon.magical`` or a spell) overcomes a target's B/P/S resistance when
# that resistance is the "nonmagical attacks" flavor (see
# ``Combatant.physical_resistances_nonmagical_only``).
_PHYSICAL_TYPES: Final[frozenset[str]] = frozenset({"bludgeoning", "piercing", "slashing"})


def _effective_resistances(
    target: Combatant, sidecar: dict[str, list[str]], *, magical: bool
) -> set[str]:
    """Static ``Combatant.damage_resistances`` + sidecar (effect-granted)
    resistances, minus the B/P/S entries a magical source overcomes.

    The nonmagical-only qualifier (``Combatant.physical_resistances_nonmagical_only``)
    applies ONLY to the static stat-block list. Effect-granted resistances
    (e.g. Rage's unconditional resistance to Bludgeoning / Piercing /
    Slashing) are always unconditional and are never bypassed by ``magical``.

    The orchestrator's ``_project_target_modifiers`` ALSO copies
    ``Combatant.damage_resistances`` into the sidecar's ``"resistances"``
    entry as a convenience (so a single sidecar dict carries every passive
    damage modifier). That copy is not itself effect-granted — it is the
    same static entry appearing twice — so it must not defeat the bypass.
    The genuinely effect-granted sidecar entries are therefore isolated by
    subtracting the target's own static list from the sidecar list BEFORE
    unioning back in; only what remains (added by an active effect, not by
    the stat block) is treated as unconditional.
    """
    static_resistances = set(target.damage_resistances)
    sidecar_resistances = set(sidecar.get("resistances", ()))
    effect_granted = sidecar_resistances - static_resistances
    if magical and target.physical_resistances_nonmagical_only:
        static_resistances -= _PHYSICAL_TYPES
    return static_resistances | effect_granted


def apply_damage(
    target: Combatant,
    rolled_by_type: dict[str, int],
    ctx: ActivityResolutionContext,
    *,
    magical: bool = False,
) -> None:
    """Apply a per-damage-type rolled amount to ``target`` and emit one
    ``DamageApplied`` per valid type.

    For each ``(damage_type, amount)``: validate the type against the SRD set
    (skip + log ``damage_type_invalid`` on miss), merge the static ``Combatant``
    resist/immune lists with the sidecar resist/immune/vuln lists, apply
    vuln→resist→immune, compute ``is_overkill``, and emit ``DamageApplied``.

    ``magical`` — the damage comes from a magic weapon (``Weapon.magical``) or
    a spell. SRD "resistance to Bludgeoning, Piercing, and Slashing from
    nonmagical attacks" does not apply to it (see
    ``Combatant.physical_resistances_nonmagical_only``); the ``"all"``
    wildcard (Petrified) and non-physical types are unaffected. This qualifier
    applies ONLY to the static stat-block resistance list — effect-granted
    (sidecar) resistances, such as Rage's, are always unconditional and are
    never bypassed by ``magical`` (see ``_effective_resistances``).
    """
    sidecar = ctx.passive_damage_modifiers.get(target.entity_id, {})
    resistances = _effective_resistances(target, sidecar, magical=magical)
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
    """Apply vuln (×2) → resist (//2 floor) → immune (⇒0) in the legacy evaluator order.

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
