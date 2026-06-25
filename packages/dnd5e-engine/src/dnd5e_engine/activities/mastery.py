"""Weapon-mastery resolution for the ``attack`` kind handler — the SRD-2024
INSTANTANEOUS subset that resolves entirely within a single attack.

``Weapon.mastery`` is a lowercase string (Foundry ``system.mastery.value``) on a
distinct axis from ``WeaponProperty``. The 2024 SRD defines eight masteries; only
the two that fully resolve inside the attack are implemented here:

* **graze** — on a MISS, deal damage equal to the attacker's governing-ability
  modifier (the SAME ability ``attack._governing_ability`` returns), of the
  weapon's damage type. No dice, no normal damage mod stacking — just the flat
  mod, and nothing when the mod is <= 0. Routed through ``apply.apply_damage`` so
  the target's resistance / immunity / vulnerability apply.
* **topple** — on a HIT, the target makes a Constitution save vs the attacker's
  mastery DC ``8 + proficiency + governing-ability mod``. The save goes through
  the same save primitive the ``save`` kind uses (honoring ``force_save_d20``) and
  emits ``SaveRolled(ability="con", ...)`` BEFORE any condition. On a FAILURE the
  target is knocked ``prone`` (``ConditionApplied``); on a success, nothing.

The remaining six masteries are lingering / multi-target / movement effects that
do NOT resolve within the attack and are deferred to a later piece. Each is
listed below with its one-line SRD reference; ``apply_mastery_*`` logs
``mastery_deferred mastery=<name>`` at INFO and applies no mechanic:

* **sap** — on hit, target has disadvantage on its next attack before your next
  turn (lingering disadvantage rider — SRD §Weapon Mastery / Sap).
* **vex** — on hit, you have advantage on your next attack against that target
  before your next turn (lingering advantage rider — SRD §Vex).
* **slow** — on hit, target's speed is reduced by 10 ft until your next turn
  (movement / speed modifier — SRD §Slow).
* **push** — on hit, you can push the target up to 10 ft straight away from you
  (forced movement, needs grid/position — SRD §Push).
* **nick** — the light-weapon extra attack is folded into the Attack action (extra
  attack economy, not an in-attack rider — SRD §Nick).
* **cleave** — on hit, a second creature within 5 ft of the target can be struck
  (multi-target chained attack — SRD §Cleave).

MIRRORS, does not import from, ``effects/``. Topple's Con save runs through the
shared ``activities/save_primitive.py:roll_save`` (the same primitive the ``save``
kind uses), so its ``force_save_d20`` determinism and modifier sourcing match;
graze has no roll. No effects/evaluator/orchestrator/neo4j imports.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from dnd5e_engine.activities.apply import apply_damage
from dnd5e_engine.activities.save_primitive import roll_save
from dnd5e_engine.events import ConditionApplied, SaveRolled

if TYPE_CHECKING:
    from dnd5e_srd_data.schema.item import Weapon

    from dnd5e_engine.types.combat import Combatant

    from .context import ActivityResolutionContext

_LOGGER = logging.getLogger(__name__)

# The instantaneous masteries this module resolves; everything else is deferred.
_GRAZE = "graze"
_TOPPLE = "topple"


def apply_mastery_on_hit(
    weapon: Weapon | None,
    ctx: ActivityResolutionContext,
    target: Combatant,
    governing_ability: str | None,
) -> None:
    """Resolve a weapon's HIT-triggered mastery against ``target``.

    Only **topple** triggers on a hit: the target makes a Con save vs the mastery
    DC and is knocked prone on a failure. Other masteries are deferred (logged).
    A weapon with no mastery is a no-op.
    """
    mastery = _mastery_of(weapon)
    if mastery is None:
        return
    if mastery == _TOPPLE:
        _resolve_topple(ctx, target, governing_ability)
        return
    if mastery == _GRAZE:
        # graze triggers on a MISS, not a hit — nothing to do on a hit.
        return
    _log_deferred(mastery)


def apply_mastery_on_miss(
    weapon: Weapon | None,
    ctx: ActivityResolutionContext,
    target: Combatant,
    governing_ability: str | None,
) -> None:
    """Resolve a weapon's MISS-triggered mastery against ``target``.

    Only **graze** triggers on a miss: deal flat governing-ability-mod damage of
    the weapon's damage type (nothing when the mod is <= 0). Other masteries are
    deferred (logged). A weapon with no mastery is a no-op.
    """
    mastery = _mastery_of(weapon)
    if mastery is None:
        return
    if mastery == _GRAZE:
        _resolve_graze(weapon, ctx, target, governing_ability)
        return
    if mastery == _TOPPLE:
        # topple triggers on a HIT, not a miss — nothing to do on a miss.
        return
    _log_deferred(mastery)


def _mastery_of(weapon: Weapon | None) -> str | None:
    """The weapon's lowercase mastery string, or ``None`` when absent."""
    if weapon is None:
        return None
    return weapon.mastery


def _log_deferred(mastery: str) -> None:
    """Mark a non-instantaneous mastery as deferred (tracked Piece-2 follow-up).

    The gap must not be SILENT: a lingering / multi-target / movement mastery
    applies no mechanic here but emits one INFO marker so the deferral is visible.
    """
    _LOGGER.info("mastery_deferred mastery=%s", mastery)


# ── graze (on miss) ──────────────────────────────────────────────────────────


def _resolve_graze(
    weapon: Weapon | None,
    ctx: ActivityResolutionContext,
    target: Combatant,
    governing_ability: str | None,
) -> None:
    """Deal flat governing-ability-mod damage of the weapon's damage type on a miss.

    SRD §Graze: on a miss, the target takes damage equal to the ability modifier
    used for the attack, of the weapon's damage type. No attack-damage mod
    stacking, no dice — just the flat mod, and nothing when it is <= 0. Routed
    through ``apply.apply_damage`` so the target's resist / immune / vuln apply.
    """
    if weapon is None or governing_ability is None:
        return
    mod = ctx.ability_mod(governing_ability)
    if mod <= 0:
        return
    damage_type = _weapon_damage_type(weapon)
    if damage_type is None:
        return
    apply_damage(target, {damage_type: mod}, ctx)


def _weapon_damage_type(weapon: Weapon) -> str | None:
    """The weapon's primary damage type (first ``damage_parts`` entry).

    SRD weapons carry a single base damage type; graze deals damage of that type.
    A weapon with no ``damage_parts`` (ill-formed data) yields ``None`` and graze
    is skipped.
    """
    if not weapon.damage_parts:
        return None
    return weapon.damage_parts[0].damage_type


# ── topple (on hit) ──────────────────────────────────────────────────────────


def _resolve_topple(
    ctx: ActivityResolutionContext,
    target: Combatant,
    governing_ability: str | None,
) -> None:
    """Force a Con save vs the mastery DC; knock prone on failure.

    SRD §Topple: on a hit, the target makes a Constitution saving throw vs DC
    ``8 + proficiency + the attack's governing-ability mod``; on a failure it is
    knocked prone. ``SaveRolled(ability="con", ...)`` is emitted BEFORE any
    condition (a topple that applies prone without first emitting SaveRolled is a
    bug). The save d20 honors ``force_save_d20`` for determinism.
    """
    dc = _topple_dc(ctx, governing_ability)
    total, succeeded = roll_save(ctx, target, "con", dc)

    ctx.event_emitter(
        SaveRolled(
            target_id=target.entity_id,
            ability="con",
            dc=dc,
            roll_total=total,
            succeeded=succeeded,
        )
    )

    if not succeeded:
        ctx.event_emitter(ConditionApplied(target_id=target.entity_id, condition="prone"))


def _topple_dc(ctx: ActivityResolutionContext, governing_ability: str | None) -> int:
    """Mastery save DC: ``8 + proficiency + governing-ability mod`` (SRD §Topple).

    The governing ability is the SAME one the attack roll used; ``None`` (a flat
    attack with no ability) contributes +0.
    """
    mod = ctx.ability_mod(governing_ability) if governing_ability is not None else 0
    return 8 + ctx.caster_proficiency_bonus + mod
