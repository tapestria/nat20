"""Weapon-mastery resolution for the ``attack`` kind handler.

``Weapon.mastery`` is a lowercase string (Foundry ``system.mastery.value``) on a
distinct axis from ``WeaponProperty``. The 2024 SRD defines eight masteries; all
eight are live. Four resolve INSIDE the attack here; the other four are
lingering / movement / multi-target riders that this pure resolver only
REPORTS through the ``ctx.mastery_procs`` writeback channel (controller
ruling R4) for the orchestrator to fold into live combat state — or, for
cleave / nick, are resolved elsewhere entirely:

* **graze** — on a MISS, deal damage equal to the attacker's governing-ability
  modifier (the SAME ability ``attack._governing_ability`` returns), of the
  weapon's damage type. No dice, no normal damage mod stacking — just the flat
  mod, and nothing when the mod is <= 0. Routed through ``apply.apply_damage`` so
  the target's resistance / immunity / vulnerability apply.
* **topple** — on a HIT, the target makes a Constitution save vs the attacker's
  mastery DC ``8 + proficiency + governing-ability mod``. The save goes through
  the same save primitive the ``save`` kind uses (honoring ``force_save_d20``) and
  emits ``SaveRolled(ability="con", ...)`` BEFORE any condition. On a FAILURE the
  target is knocked ``prone`` (``ConditionApplied``) UNLESS the target is immune
  to the ``prone`` condition (``effects.is_condition_immune`` — the save still
  rolls and ``SaveRolled`` still fires; only the emit is gated, C15 Task 6).
* **vex** (C15 Task 6) — on a HIT that DEALS DAMAGE (the post-immunity total,
  ``apply_damage``'s return), append ``("vex", target_id)`` to
  ``ctx.mastery_procs``. The orchestrator folds the proc into a lingering
  Advantage grant ("before the end of your next turn") after resolution.
* **sap** (C15 Task 6) — on a HIT (damage irrelevant), append
  ``("sap", target_id)``. The orchestrator folds it into a lingering
  Disadvantage mark on the TARGET ("before the start of your next turn").
* **slow** (C15 Task 7) — SRD: "If you hit a creature with this weapon and
  deal damage to it, you can reduce its Speed by 10 feet until the start of
  your next turn. If the creature is hit more than once by weapons that have
  this property, the Speed reduction doesn't exceed 10 feet." On a HIT that
  DEALS DAMAGE, append ``("slow", target_id)``; the orchestrator folds it
  into ``live.slow_marks`` (a flat, non-stacking -10 ft on the target's
  effective Speed, cleared at the SOURCE attacker's next turn start).
* **push** (C15 Task 7) — SRD: "If you hit a creature with this weapon, you
  can push the creature up to 10 feet straight away from yourself if it is
  Large or smaller." On a HIT (damage irrelevant), append
  ``("push", target_id)``; the orchestrator folds it into a
  ``push_combatant(..., 10)`` forced move (controller ruling R5: always the
  full 10 ft). The "Large or smaller" size gate is NOT modelled — creature
  size is not a ``Combatant`` attribute yet (see ``BACKLOG.md``, the
  Grapple/Shove/Push size-gate entry), so every target is pushed.
* **cleave** (C15 Task 7) — resolved in ``attack.py`` itself (the chained
  second attack roll needs the attack machinery: to-hit, d20, damage), gated
  by the orchestrator-precomputed ``ctx.cleave_available`` /
  ``ctx.cleave_candidate``. Nothing to do here on the main hit; the chained
  roll never re-enters this module.
* **nick** (C15 Task 7) — pure action-economy: the orchestrator's off-hand
  consume path (``_consume_offhand_attack_budget``) leaves the Bonus Action
  unspent when the off-hand weapon carries ``nick``. No in-attack rider.

Topple's Con save runs through the shared
``activities/save_primitive.py:roll_save`` (the same primitive the ``save``
kind uses), so its ``force_save_d20`` determinism and modifier sourcing match;
graze has no roll. The one import from ``effects/`` (``is_condition_immune``)
is the shared condition-immunity gate (C15 Task 6) — otherwise this module
still does not import evaluator/orchestrator/neo4j machinery.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dnd5e_engine.activities.apply import apply_damage
from dnd5e_engine.activities.effects import is_condition_immune
from dnd5e_engine.activities.save_primitive import roll_save
from dnd5e_engine.events import ConditionApplied, SaveRolled

if TYPE_CHECKING:
    from dnd5e_srd_data.schema.item import Weapon

    from dnd5e_engine.types.combat import Combatant

    from .context import ActivityResolutionContext

# The masteries this module resolves or reports. ``cleave`` (attack.py) and
# ``nick`` (orchestrator off-hand economy) never route through here.
_GRAZE = "graze"
_TOPPLE = "topple"
_VEX = "vex"
_SAP = "sap"
_SLOW = "slow"
_PUSH = "push"


def apply_mastery_on_hit(
    weapon: Weapon | None,
    ctx: ActivityResolutionContext,
    target: Combatant,
    governing_ability: str | None,
    *,
    damage_dealt: int = 0,
) -> None:
    """Resolve a weapon's HIT-triggered mastery against ``target``.

    **topple** — the target makes a Con save vs the mastery DC and is knocked
    prone (immunity-gated) on a failure. **vex** — a hit that DEALT damage
    (``damage_dealt > 0``, the post-immunity total from ``apply_damage``)
    appends a proc to ``ctx.mastery_procs`` for the orchestrator to fold into
    a lingering Advantage grant. **sap** — any hit appends a proc for a
    lingering Disadvantage mark on ``target``. **slow** — a hit that DEALT
    damage appends a proc for the -10 ft Speed mark. **push** — any hit
    appends a proc for the 10-ft forced move. graze (miss-only), cleave
    (``attack.py``) and nick (orchestrator) have nothing to do here. A weapon
    with no mastery is a no-op.

    ``damage_dealt`` is the caller's (``attack.py``) already-computed total —
    this resolver never re-derives it, keeping the "dealt damage" definition
    (post-resistance/immunity) in exactly one place.
    """
    mastery = _mastery_of(weapon)
    if mastery is None:
        return
    if mastery == _TOPPLE:
        _resolve_topple(ctx, target, governing_ability)
        return
    if mastery == _VEX:
        # SRD §Vex: "hit a creature ... and deal damage to the creature" — a
        # hit that dealt ZERO final damage (e.g. a damage-immune target)
        # does not proc the rider.
        if damage_dealt > 0:
            ctx.mastery_procs.append((_VEX, target.entity_id))
        return
    if mastery == _SAP:
        # SRD §Sap: "hit a creature with this weapon" — damage-independent.
        ctx.mastery_procs.append((_SAP, target.entity_id))
        return
    if mastery == _SLOW:
        # SRD §Slow: "hit a creature with this weapon and deal damage to it"
        # — same damage-dealt gate as vex (zero final damage = no proc).
        if damage_dealt > 0:
            ctx.mastery_procs.append((_SLOW, target.entity_id))
        return
    if mastery == _PUSH:
        # SRD §Push: "If you hit a creature with this weapon" — damage-
        # independent, like sap. Size gate unmodelled (module docstring).
        ctx.mastery_procs.append((_PUSH, target.entity_id))
        return
    # graze triggers on a MISS, not a hit; cleave resolves in attack.py; nick
    # is orchestrator action-economy — nothing to do on a hit for any of them.


def apply_mastery_on_miss(
    weapon: Weapon | None,
    ctx: ActivityResolutionContext,
    target: Combatant,
    governing_ability: str | None,
) -> None:
    """Resolve a weapon's MISS-triggered mastery against ``target``.

    Only **graze** triggers on a miss: deal flat governing-ability-mod damage of
    the weapon's damage type (nothing when the mod is <= 0). Every other
    mastery is HIT-triggered — nothing to do on a miss. A weapon with no
    mastery is a no-op.
    """
    if _mastery_of(weapon) == _GRAZE:
        _resolve_graze(weapon, ctx, target, governing_ability)


def _mastery_of(weapon: Weapon | None) -> str | None:
    """The weapon's lowercase mastery string, or ``None`` when absent."""
    if weapon is None:
        return None
    return weapon.mastery


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
    apply_damage(
        target,
        {damage_type: mod},
        ctx,
        magical=weapon.magical,
        source_id="mastery:graze",
        is_crit=False,
    )


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

    C15 Task 6: SRD §Immunity — "Immunity to a condition means you aren't
    affected by it." The save STILL rolls (and ``SaveRolled`` still fires)
    against a prone-immune target; only the ``ConditionApplied`` emit is
    gated by the shared ``is_condition_immune`` helper.
    """
    dc = _topple_dc(ctx, governing_ability)
    roll = roll_save(ctx, target, "con", dc)

    ctx.event_emitter(
        SaveRolled(
            target_id=target.entity_id,
            ability="con",
            dc=dc,
            roll_total=roll.total,
            succeeded=roll.succeeded,
            advantage=roll.mode,
            natural=roll.natural,
            modifier=roll.modifier,
            sources=list(roll.sources),
        )
    )

    if not roll.succeeded and not is_condition_immune(target, "prone"):
        ctx.event_emitter(ConditionApplied(target_id=target.entity_id, condition="prone"))


def _topple_dc(ctx: ActivityResolutionContext, governing_ability: str | None) -> int:
    """Mastery save DC: ``8 + proficiency + governing-ability mod`` (SRD §Topple).

    The governing ability is the SAME one the attack roll used; ``None`` (a flat
    attack with no ability) contributes +0.
    """
    mod = ctx.ability_mod(governing_ability) if governing_ability is not None else 0
    return 8 + ctx.caster_proficiency_bonus + mod
