"""Combat evaluator event union.

Per ``docs/agent-prompts/combat/00-evaluator-scaffold.md``. Exhaustively
defined here so per-effect implementers + scenario authors do NOT extend
the union at runtime; any new event type lands as a scaffold-extension
PR that updates this module first.

Typed-semantics rule (CLAUDE.md): every field over a closed set is a
``Literal[...]`` or dedicated enum, never bare ``str``.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from dnd5e_engine.types.effects import ActiveEffect

# ── canonical closed-set aliases ────────────────────────────────────────────

DamageType = Literal[
    "acid",
    "bludgeoning",
    "cold",
    "fire",
    "force",
    "lightning",
    "necrotic",
    "piercing",
    "poison",
    "psychic",
    "radiant",
    "slashing",
    "thunder",
]

Ability = Literal["str", "dex", "con", "int", "wis", "cha"]

ConditionType = Literal[
    "blinded",
    "charmed",
    "deafened",
    "exhaustion",
    "frightened",
    "grappled",
    "incapacitated",
    "invisible",
    "paralyzed",
    "petrified",
    "poisoned",
    "prone",
    "restrained",
    "stunned",
    "unconscious",
]

AdvantageMode = Literal["advantage", "disadvantage", "normal"]

EffectExpiryReason = Literal[
    "duration",
    "concentration_drop",
    "remove_ieffect",
    "combat_end",
    "dispelled",
    "source_dead",
    "moved",
]

CastFailedReason = Literal[
    "out_of_range",
    "no_slot",
    "target_invalid",
    "concentration_blocked",
    "components_missing",
    "no_action_economy",
]

IntentType = Literal[
    "attack",
    "cast_spell",
    "use_item",
    "move",
    "dash",
    "dodge",
    "disengage",
    "hide",
    "help",
    "ready",
    "reaction",
    "move_mark",
    "use_feature",
    "pass",
]


# ── round / turn structure ──────────────────────────────────────────────────


class RoundStarted(BaseModel):
    type: Literal["round_started"] = "round_started"
    round_number: int


class RoundEnded(BaseModel):
    type: Literal["round_ended"] = "round_ended"
    round_number: int


class TurnStarted(BaseModel):
    type: Literal["turn_started"] = "turn_started"
    actor_id: str


class TurnEnded(BaseModel):
    type: Literal["turn_ended"] = "turn_ended"
    actor_id: str


class IntentSubmitted(BaseModel):
    type: Literal["intent_submitted"] = "intent_submitted"
    actor_id: str
    intent_type: IntentType
    # Intent-type-specific fields are implementer-extensible; the
    # discriminator + actor_id + intent_type are the stable contract.
    spell_id: str | None = None
    target_id: str | None = None
    item_id: str | None = None


# ── roll resolution ─────────────────────────────────────────────────────────


class AttackRolled(BaseModel):
    type: Literal["attack_rolled"] = "attack_rolled"
    attacker_id: str
    target_id: str
    roll_total: int
    advantage: AdvantageMode
    is_crit: bool
    is_hit: bool
    # SRD §Opportunity Attacks — *"You can make an opportunity attack when a
    # hostile creature that you can see moves out of your Reach."* The AoO is
    # mechanically identical to a regular Melee Attack roll, so it rides the
    # same event shape. ``True`` marks the attack as triggered by the
    # reactor's Reaction (interrupting the mover's MOVE intent) rather than
    # the attacker's own Action. Consumed by the WS client + future monster-
    # AoO path when the reaction queue lands.
    is_opportunity_attack: bool = False


class SaveRolled(BaseModel):
    type: Literal["save_rolled"] = "save_rolled"
    target_id: str
    ability: Ability
    dc: int
    roll_total: int
    succeeded: bool


class CheckRolled(BaseModel):
    type: Literal["check_rolled"] = "check_rolled"
    actor_id: str
    ability: Ability
    skill: str | None
    dc: int | None
    roll_total: int
    succeeded: bool | None


# ── damage / healing / temp HP ──────────────────────────────────────────────


class DamageApplied(BaseModel):
    type: Literal["damage_applied"] = "damage_applied"
    target_id: str
    amount: int
    damage_type: DamageType
    is_overkill: bool


class HealingApplied(BaseModel):
    type: Literal["healing_applied"] = "healing_applied"
    target_id: str
    amount: int


class TempHpApplied(BaseModel):
    type: Literal["temphp_applied"] = "temphp_applied"
    target_id: str
    amount: int


# ── effects + conditions ────────────────────────────────────────────────────


class EffectApplied(BaseModel):
    type: Literal["effect_applied"] = "effect_applied"
    effect: ActiveEffect
    # statuses live on `effect.statuses`; no separate field — there is
    # no bridge step in Phase 6.


class EffectExpired(BaseModel):
    type: Literal["effect_expired"] = "effect_expired"
    effect_id: str
    target_id: str
    origin: str
    reason: EffectExpiryReason


class ConditionApplied(BaseModel):
    type: Literal["condition_applied"] = "condition_applied"
    target_id: str
    condition: ConditionType


class ConditionRemoved(BaseModel):
    type: Literal["condition_removed"] = "condition_removed"
    target_id: str
    condition: ConditionType


# ── concentration ───────────────────────────────────────────────────────────


class ConcentrationCheck(BaseModel):
    type: Literal["concentration_check"] = "concentration_check"
    target_id: str
    dc: int
    roll_total: int
    succeeded: bool


class ConcentrationDropped(BaseModel):
    type: Literal["concentration_dropped"] = "concentration_dropped"
    target_id: str
    effect_name: str


# ── death + stabilization ───────────────────────────────────────────────────


class Unconscious(BaseModel):
    type: Literal["unconscious"] = "unconscious"
    target_id: str


class DeathSaveStarted(BaseModel):
    type: Literal["death_save_started"] = "death_save_started"
    target_id: str


class DeathSaveRolled(BaseModel):
    type: Literal["death_save_rolled"] = "death_save_rolled"
    target_id: str
    roll_total: int
    outcome: Literal["success", "failure", "crit_success", "crit_failure"]
    running_successes: int
    running_failures: int


class Stabilized(BaseModel):
    type: Literal["stabilized"] = "stabilized"
    target_id: str


class Death(BaseModel):
    type: Literal["death"] = "death"
    target_id: str
    reason: Literal["damage", "death_saves", "instant_kill"]


# ── movement / zones ────────────────────────────────────────────────────────


class ZoneTransit(BaseModel):
    type: Literal["zone_transit"] = "zone_transit"
    actor_id: str
    from_zone: str
    to_zone: str
    feet_spent: int


class ActorMoved(BaseModel):
    """Emitted when a MOVE intent successfully shifts an actor to an adjacent zone.

    Distinct from ``ZoneTransit`` (an evaluator-internal "I moved this many
    feet" notification for AOE/ranged geometry handlers): ``ActorMoved`` is
    the orchestrator-emitted, intent-driven event the WS projection and
    narrator consume. Movement does NOT end the turn — the actor may still
    take Action / Bonus Action / etc.
    """

    type: Literal["actor_moved"] = "actor_moved"
    actor_id: str
    from_zone: str
    to_zone: str
    distance_ft: int


class DashTaken(BaseModel):
    """Emitted when a Dash intent succeeds.

    SRD §Combat — Dash: the actor's movement budget is doubled for the
    current turn (``movement_remaining += base_speed``). ``budget_consumed``
    captures whether the Dash was taken as the Action (default) or as the
    Rogue's Cunning Action Bonus Action. Dash does NOT advance the turn —
    the actor keeps initiative and may follow with MOVE / other intents.
    """

    type: Literal["dash_taken"] = "dash_taken"
    actor_id: str
    doubled_movement_remaining: int
    budget_consumed: Literal["action", "bonus_action"]


class MoveFailed(BaseModel):
    """Emitted when a MOVE intent is rejected post-validation.

    Mirrors ``CastFailed`` for movement: the actor keeps the turn, no
    budget is consumed, and the failure surfaces a typed reason the WS
    client can branch on.
    """

    type: Literal["move_failed"] = "move_failed"
    actor_id: str
    reason: Literal["not_adjacent", "insufficient_movement", "combat_ended", "not_actor_turn"]


class AttackFailed(BaseModel):
    """Emitted when an ATTACK intent is rejected pre-evaluation.

    Mirrors ``CastFailed`` for weapon attacks: the actor keeps the turn,
    no action budget is consumed, and the failure surfaces a typed
    reason. ``out_of_range`` fires when the target's zone is farther
    than the weapon's reach (melee) or normal range (ranged) along the
    zone graph; ``target_invalid`` covers missing-target / non-combatant
    target cases; ``no_action_economy`` mirrors the spell path's gate
    for parity.
    """

    type: Literal["attack_failed"] = "attack_failed"
    actor_id: str
    target_id: str | None
    reason: Literal["out_of_range", "target_invalid", "no_action_economy"]


# ── spell / reaction outcomes ───────────────────────────────────────────────


class CastFailed(BaseModel):
    type: Literal["cast_failed"] = "cast_failed"
    actor_id: str
    spell_id: str
    reason: CastFailedReason


class ReactionTriggered(BaseModel):
    type: Literal["reaction_triggered"] = "reaction_triggered"
    actor_id: str
    reaction_name: str
    trigger_event_uuid: str


# ── combat lifecycle ────────────────────────────────────────────────────────


class CombatEnded(BaseModel):
    type: Literal["combat_ended"] = "combat_ended"
    reason: Literal["victory", "defeat_tpk", "flee", "forced"]


CombatEvent = Annotated[
    RoundStarted
    | RoundEnded
    | TurnStarted
    | TurnEnded
    | IntentSubmitted
    | AttackRolled
    | SaveRolled
    | CheckRolled
    | DamageApplied
    | HealingApplied
    | TempHpApplied
    | EffectApplied
    | EffectExpired
    | ConditionApplied
    | ConditionRemoved
    | ConcentrationCheck
    | ConcentrationDropped
    | Unconscious
    | DeathSaveStarted
    | DeathSaveRolled
    | Stabilized
    | Death
    | ZoneTransit
    | ActorMoved
    | DashTaken
    | MoveFailed
    | AttackFailed
    | CastFailed
    | ReactionTriggered
    | CombatEnded,
    Field(discriminator="type"),
]


# Exhaustive registry — used by the smoke test to assert no orphan
# subclasses; per-effect implementers consult it to confirm an event
# they want to emit is reachable from the union.
ALL_COMBAT_EVENT_TYPES: tuple[type[BaseModel], ...] = (
    RoundStarted,
    RoundEnded,
    TurnStarted,
    TurnEnded,
    IntentSubmitted,
    AttackRolled,
    SaveRolled,
    CheckRolled,
    DamageApplied,
    HealingApplied,
    TempHpApplied,
    EffectApplied,
    EffectExpired,
    ConditionApplied,
    ConditionRemoved,
    ConcentrationCheck,
    ConcentrationDropped,
    Unconscious,
    DeathSaveStarted,
    DeathSaveRolled,
    Stabilized,
    Death,
    ZoneTransit,
    ActorMoved,
    DashTaken,
    MoveFailed,
    AttackFailed,
    CastFailed,
    ReactionTriggered,
    CombatEnded,
)


__all__ = [
    "ALL_COMBAT_EVENT_TYPES",
    "Ability",
    "ActorMoved",
    "AdvantageMode",
    "AttackFailed",
    "AttackRolled",
    "CastFailed",
    "CastFailedReason",
    "CheckRolled",
    "CombatEnded",
    "CombatEvent",
    "ConcentrationCheck",
    "ConcentrationDropped",
    "ConditionApplied",
    "ConditionRemoved",
    "ConditionType",
    "DamageApplied",
    "DamageType",
    "DashTaken",
    "Death",
    "DeathSaveRolled",
    "DeathSaveStarted",
    "EffectApplied",
    "EffectExpired",
    "EffectExpiryReason",
    "HealingApplied",
    "IntentSubmitted",
    "IntentType",
    "MoveFailed",
    "ReactionTriggered",
    "RoundEnded",
    "RoundStarted",
    "SaveRolled",
    "Stabilized",
    "TempHpApplied",
    "TurnEnded",
    "TurnStarted",
    "Unconscious",
    "ZoneTransit",
]
