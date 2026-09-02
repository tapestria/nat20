"""Combat evaluator event union.

Exhaustively
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

# F2 — the typed provenance of a single advantage/disadvantage contribution
# feeding ``activities.d20.roll_d20_test``. SRD 5.2 "Advantage and
# Disadvantage" only cares about presence, not count or source, but the
# engine tracks source for narration + future rules interactions (e.g.
# Reliable Talent, Elven Accuracy) that key off *which* source applied.
AdvantageSource = Literal[
    "flag",
    "effect",
    "condition:attacker",
    "condition:target",
    "cover",
    "range:long",
    "ranged_in_melee",
    "unseen",
    "dodge",
    "help",
    "trait",
]

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
    # SRD 5.2 Counterspell — "On a failed save, the spell dissipates with no
    # effect, and the action, Bonus Action, or Reaction used to cast it is
    # wasted." Emitted by the pre-armed reaction queue (orchestrator.py,
    # when a queued Counterspell's Constitution save fails.
    "countered",
    # SRD 5.2 §Limited-Use Features — a capped, rest-recharged
    # feature (Second Wind) invoked again with no uses left and no intervening
    # rest. Mirrors the ``no_action_economy`` reject shape, extended from a
    # per-turn budget to a per-encounter / per-rest one.
    "no_uses_remaining",
    # SRD 5.2 §Charges — a charged item invoked with fewer charges remaining
    # than the activity's cost (``consumption.targets[type=itemUses]``).
    "no_charges_remaining",
    # A variable-charge invocation that violates the activity's
    # ``consumption.scaling`` contract (not allowed, below base cost, or
    # above the evaluated max). Emitted by the use_item charge gate.
    "invalid_charge_spend",
    # SRD 5.2 Charmed — "You can't attack the charmer or target the
    # charmer with damaging abilities or magical effects." (C12)
    "target_is_charmer",
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
    "drop_concentration",
    # C14 Task 6/7 — Unarmed Strike options (SRD 5.2 §Actions in Combat) and
    # the SRD 5.2 "Ending a Grapple" escape action. All four land together so
    # a later task adding shove/stand_up handlers needs no events.py edit.
    "grapple",
    "shove",
    "stand_up",
    "escape_grapple",
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


#: The three turn-boundary phases the engine runs hooks at
#: (``dnd5e_engine.turn_lifecycle``). ``round_start`` fires once per round on
#: the initiative wrap; ``turn_start`` / ``turn_end`` bracket each actor's turn.
TurnPhaseName = Literal["round_start", "turn_start", "turn_end"]


class TurnPhase(BaseModel):
    """Marker for a turn-boundary phase — emitted around every turn edge.

    Purely informational: it carries no rules outcome of its own. It marks the
    point in the stream at which the engine ran that phase's lifecycle hooks,
    so a host can render "top of round 3" / "end of Alice's turn" without
    inferring boundaries from ``TurnStarted``/``TurnEnded`` adjacency, and so
    boundary effects (ongoing damage, regeneration, recharge) are attributable
    to a phase rather than to whichever event happened to precede them.

    ``actor_id`` is the actor whose turn is starting or ending, and ``None``
    for ``round_start``. Ordering at a turn boundary is fixed::

        TurnPhase(turn_end, A) -> [turn_end hooks] -> TurnEnded(A)
        -> (on wrap) RoundStarted -> TurnPhase(round_start) -> [round_start hooks]
        -> TurnStarted(B) -> TurnPhase(turn_start, B) -> [turn_start hooks]
    """

    type: Literal["turn_phase"] = "turn_phase"
    actor_id: str | None
    phase: TurnPhaseName
    round_number: int


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
    # F2 — optional D20 Test provenance (``activities.d20.D20Result``).
    # Additive: unset by pre-F2 callers (e.g. the opportunity-attack path);
    # populated by ``activities/attack.py::resolve_attack`` since F2b.
    # ``natural`` is the KEPT die after advantage — the face actually used
    # for the total once advantage/disadvantage has picked higher/lower, and
    # the die the natural-20 crit / natural-1 fumble test reads. Under
    # advantage/disadvantage it is therefore NOT the first draw; the
    # discarded die is not currently reported (``D20Result.first`` holds it
    # inside the resolver).
    natural: int | None = None
    # ``modifier`` is the FLAT attack bonus (ability mod + proficiency +
    # parsed ``attack.bonus`` + the weapon's magical bonus). It deliberately
    # EXCLUDES the per-attacker ``passive_attack_bonus`` dice sidecar (SRD
    # §Bless / §Bane, a signed d4 rolled fresh per swing): folding that into
    # the primitive's modifier would change the seeded draw ORDER. So
    # ``roll_total == natural + modifier`` holds only when no Bless/Bane-style
    # sidecar is active on the attacker; with one, the difference is the d4.
    # A separate ``bonus_dice_total`` field is deferred.
    modifier: int | None = None
    sources: list[AdvantageSource] = Field(default_factory=list)


class SaveRolled(BaseModel):
    type: Literal["save_rolled"] = "save_rolled"
    target_id: str
    ability: Ability
    dc: int
    roll_total: int
    succeeded: bool
    # F2 — the resolved D20 Test mode, matching ``AttackRolled.advantage``.
    # Defaults to ``"normal"`` so pre-F2 constructors stay valid.
    advantage: AdvantageMode = "normal"
    # F2 — optional D20 Test provenance; see ``AttackRolled``.
    natural: int | None = None
    modifier: int | None = None
    sources: list[AdvantageSource] = Field(default_factory=list)


class CheckRolled(BaseModel):
    type: Literal["check_rolled"] = "check_rolled"
    actor_id: str
    ability: Ability
    skill: str | None
    dc: int | None
    roll_total: int
    succeeded: bool | None
    # F2 — the resolved D20 Test mode, matching ``AttackRolled.advantage``.
    # Defaults to ``"normal"`` so pre-F2 constructors stay valid.
    advantage: AdvantageMode = "normal"
    # F2 — optional D20 Test provenance; see ``AttackRolled``.
    natural: int | None = None
    modifier: int | None = None
    sources: list[AdvantageSource] = Field(default_factory=list)


# ── damage / healing / temp HP ──────────────────────────────────────────────


class DamageApplied(BaseModel):
    type: Literal["damage_applied"] = "damage_applied"
    target_id: str
    amount: int
    damage_type: DamageType
    is_overkill: bool
    # C15 — damage-source attribution: weapon slug / synthesized activity id /
    # ``"mastery:<slug>"`` for procs. ``None`` for paths not yet threaded
    # (spell/save/heal damage — a C17+ seam).
    source_id: str | None = None
    # C15 — whether this damage event was a critical hit; feeds the
    # crit-at-0-HP two-death-save-failures clause (SRD §Damage at 0 HP).
    is_crit: bool = False


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
    # no bridge step in .


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
    """SRD 5.2 §Concentration — the Constitution save a concentrating
    creature makes when it takes damage (``DC = 10 or half the damage
    taken, whichever is higher``). Emitted by the orchestrator's
    concentration-on-damage block since F2c.

    TRANSITIONAL: emitted alongside ``SaveRolled(ability='con')`` until
    v0.7. The generic ``SaveRolled`` is the shape hosts consumed before
    this event was wired, so both are emitted for one release; hosts that
    count saves must filter one of them out.
    """

    type: Literal["concentration_check"] = "concentration_check"
    target_id: str
    dc: int
    roll_total: int
    succeeded: bool
    # F2 — the resolved D20 Test mode, matching ``AttackRolled.advantage``.
    advantage: AdvantageMode = "normal"
    # F2 — optional D20 Test provenance; see ``AttackRolled``. Carried here as
    # well as on the twin ``SaveRolled`` so the breakdown survives the v0.7
    # removal of that duplicate.
    natural: int | None = None
    modifier: int | None = None
    sources: list[AdvantageSource] = Field(default_factory=list)


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
    """Emitted when a MOVE intent successfully shifts an actor to the requested
    cell/zone (one event per intent, ``distance_ft`` = total feet spent).

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


class CombatantMoved(BaseModel):
    """Emitted when the ENGINE relocates a combatant outside a MOVE intent —
    forced movement (Thunderwave's "pushed 10 feet away from you", the Push
    weapon mastery, Shove). ``forced=True`` for every emitter today; the flag
    exists so a future non-forced engine relocation (teleport riders) can reuse
    the event without a new type. Intent-driven moves stay ``ActorMoved``.
    Forced movement consumes no movement budget and provokes no opportunity
    attack (SRD 5.2 §Opportunity Attacks: "You also don't provoke an
    Opportunity Attack when … something moves you without using your movement").
    """

    type: Literal["combatant_moved"] = "combatant_moved"
    actor_id: str
    from_zone: str
    to_zone: str
    distance_ft: int
    forced: bool


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
    reason: Literal[
        "not_adjacent",
        "insufficient_movement",
        "combat_ended",
        "not_actor_turn",
        # C16 — multi-cell moves (SRD 5.2 §Movement and Position, "Playing on a Grid").
        "unreachable",  # no legal route (walls / blocked cells / enemies box the mover in)
        "occupied",  # "You can't willingly end a move in a space occupied by another creature."
        "blocked_path",  # the single requested step crosses a wall or cuts a blocked corner
        # SRD 5.2 "Speed 0" conditions (Grappled / Restrained / Paralyzed /
        # Petrified / Unconscious) or Exhaustion reducing Speed to 0 (C12).
        "speed_zero",
    ]


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
    reason: Literal[
        "out_of_range",
        "target_invalid",
        "no_action_economy",
        # SRD 5.2 Charmed — "You can't attack the charmer or target the
        # charmer with damaging abilities or magical effects." (C12)
        "target_is_charmer",
    ]


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
    | TurnPhase
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
    | CombatantMoved
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
    TurnPhase,
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
    CombatantMoved,
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
    "AdvantageSource",
    "AttackFailed",
    "AttackRolled",
    "CastFailed",
    "CastFailedReason",
    "CheckRolled",
    "CombatEnded",
    "CombatEvent",
    "CombatantMoved",
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
    "TurnPhase",
    "TurnPhaseName",
    "TurnStarted",
    "Unconscious",
    "ZoneTransit",
]
