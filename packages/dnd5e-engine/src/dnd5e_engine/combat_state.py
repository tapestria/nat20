"""A combat as plain, serializable state, and the calls that resolve against it.

Contract 03 of the host this fork serves ("Rules Engine port") makes the engine
stateless: every call receives the full state it needs and a seed, and returns
its results; nothing is kept between calls. ``CombatState`` is that state for a
combat in progress. It round-trips through JSON without loss
(``CombatState.model_validate_json(state.model_dump_json()) == state``), and
every call here takes one, plus a seed, and returns a ``CombatStep``: the events
the call emitted and the new state. Nothing is registered, cached or left in
the engine when a call returns, and every die comes from
``random.Random(seed)``: never the global ``random`` module, never the clock.

``CombatState`` holds everything the engine reads on a later call:

- the round, the initiative order and the active combatant;
- each combatant (``Combatant``: its statistics, hit points, conditions, death
  saving throws, turn resources and reaction), its position, temporary hit
  points and spell slots;
- every active effect, the concentration each caster holds and the rounds
  left on it, and every pending end-of-turn repeat save;
- each readied reaction;
- each monster's spent recharge actions, per-day uses and legendary pools;
- the events of the turn in progress, which the turn's end reads ("until the
  end of your next turn", Rage's extension).

What it leaves out cannot change a later call:

- the dice stream (``_LiveCombat.rng``): each call draws from its own seed;
- undelivered events (``_LiveCombat.event_queue``): a call returns its events;
- the event log before the turn in progress: its only cross-call readers,
  ``_current_turn_events`` and ``_effect_applied_during_current_turn``, stop at
  the ending actor's ``TurnStarted``, and every other reader slices from a
  count taken inside one call; ``legendary_resistance_applied_event_indices``
  is rebased to the kept tail;
- the per-call event listeners, and the turn-boundary hooks, which are code:
  the default hooks are registered again on load.

The handle API (``start_combat`` and the calls that take a ``CombatHandle``)
runs on the same resolution code. ``load_combat`` turns a state into a handle
and ``combat_state_of`` reads a handle's state back, so a host can move between
the two.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
from collections.abc import Sequence
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from dnd5e_engine.activities.conjuration import StatBlockMagnitudes, TransformSource
from dnd5e_engine.events import CombatEvent, TurnStarted
from dnd5e_engine.lingering import LingeringSpell
from dnd5e_engine.orchestrator import (
    _REGISTRY,
    CombatHandle,
    IntentRejectedError,
    PlayerIntent,
    ReactionTrigger,
    _advance_monster_turn,
    _arm_legendary_resistance,
    _begin_turn,
    _close_combat,
    _Construct,
    _get_live,
    _LiveCombat,
    _open_combat,
    _PendingReaction,
    _register_default_turn_hooks,
    _submit_player_intent,
    _Summon,
    _Transform,
)
from dnd5e_engine.outcome import CombatOutcome, DeathRecord
from dnd5e_engine.reactions import (
    ReactionChoice,
    ReactionDecision,
    ReactionPolicy,
    ReactionPrompt,
    ReactionSuspended,
)
from dnd5e_engine.spatial import GridTopology
from dnd5e_engine.specs import EncounterMemberSpec, GridScene, PartyMemberSpec
from dnd5e_engine.types.combat import Combatant, MonsterActionUses
from dnd5e_engine.types.effects import ActiveEffect

__all__ = [
    "CombatCall",
    "CombatState",
    "CombatStep",
    "CombatSuspension",
    "ConstructState",
    "Continuation",
    "EffectKey",
    "EndCombatStep",
    "LegendaryWindow",
    "MonsterActionUsesState",
    "ReadiedReaction",
    "RepeatSave",
    "SummonState",
    "TransformState",
    "TurnKey",
    "arm_legendary_resistance",
    "begin_combat",
    "cast_outside_combat",
    "close_combat",
    "combat_state_of",
    "load_combat",
    "resolve_intent",
    "resolve_monster_turn",
    "resume",
    "start_turn",
    "state_digest",
]

#: Bumped whenever a field changes meaning, so a stored state never loads
#: into an engine that would read it differently.
STATE_VERSION: Literal[1] = 1

_EVENTS: TypeAdapter[list[CombatEvent]] = TypeAdapter(list[CombatEvent])


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EffectKey(_Model):
    """One effect instance on one creature: the engine's ``(target_id,
    effect.id, effect.origin)`` identity, so two casters' Bless on one target
    stay two effects."""

    target_id: str
    effect_id: str
    origin: str

    @classmethod
    def of(cls, key: tuple[str, str, str]) -> EffectKey:
        return cls(target_id=key[0], effect_id=key[1], origin=key[2])

    def key(self) -> tuple[str, str, str]:
        return (self.target_id, self.effect_id, self.origin)


class TurnKey(_Model):
    """A turn, named by its round and the creature whose turn it was."""

    round: int
    actor_id: str


class LegendaryWindow(_Model):
    """SRD 5.2 Legendary Actions: "Only one Legendary Action can be used at a
    time, and only immediately after another creature's turn." One window, the
    end of ``ended_actor_id``'s turn in ``round``, in which ``monster_id`` has
    already taken one."""

    round: int
    ended_actor_id: str
    monster_id: str


class RepeatSave(_Model):
    """A save the target repeats at the end of each of its turns, ending the
    condition on a success (SRD 5.2 Hold Person: "At the end of each of its
    turns, the target repeats the save")."""

    ability: str
    dc: int
    condition: str
    caster_id: str
    #: The effect's display name. Recorded with the save, never read back.
    effect_name: str | None = None


class RepeatSaves(_Model):
    effect: EffectKey
    saves: list[RepeatSave]


class EffectConditions(_Model):
    """The conditions one effect instance applied to its target, removed with
    it when it ends."""

    effect: EffectKey
    conditions: list[str]


class ReadiedReaction(_Model):
    """A reaction armed with the ``ready`` intent, fired the next time its
    trigger is observed."""

    owner_id: str
    trigger: ReactionTrigger
    spell_id: str | None
    slot_level: int | None


class MonsterActionUsesState(_Model):
    """One monster action's limited uses: a Recharge action spent and not yet
    recharged, and its per-day uses left."""

    recharge_spent: bool = False
    uses_remaining: dict[str, int] = Field(default_factory=dict)


class ConstructState(_Model):
    """A caster-owned spell construct (SRD 5.2 Spiritual Weapon's force)."""

    construct_id: str
    owner_id: str
    spell_id: str
    cell: str
    slot_level: int
    anchor: EffectKey
    cast_round: int


class TransformState(_Model):
    """A live transformation (SRD 5.2 Wild Shape, Polymorph). ``stash`` holds
    the creature's own value of every ``Combatant`` field its form replaced, in
    that field's JSON form."""

    entity_id: str
    form_slug: str
    source: TransformSource
    effect_id: str
    origin: str
    stash: dict[str, Any]
    original_monster_slug: str | None
    original_action_uses: dict[str, MonsterActionUsesState] | None
    form_proficiency_bonus: int
    attacks_per_action: int
    clears_temp_hp_on_end: bool


class SummonMagnitudes(_Model):
    ability_scores: dict[str, int]
    proficiency_bonus: int
    attack_bonus: int | None = None
    attack_damage_bonus: int = 0


class SummonState(_Model):
    """A summoned creature in the initiative order (SRD 5.2 Summon Dragon's
    Draconic Spirit). The creature itself is one of ``CombatState.combatants``."""

    entity_id: str
    owner_id: str
    spell_id: str
    stat_block_slug: str
    slot_level: int
    anchor: EffectKey
    magnitudes: SummonMagnitudes
    attacks_per_action: int


class CombatState(_Model):
    """Everything a combat in progress needs for its next call.

    Field groups, in the order SRD 5.2's "Combat" chapter meets them:

    - **Order of combat.** ``round``; ``combatants``, the initiative order;
      ``turn_index``, the slot whose turn it is; ``active_combatant``, the
      creature whose turn has started. Each ``Combatant`` carries its
      ``initiative``, hit points, conditions, ``death_saves``, and its turn
      resources: ``action_available``, ``bonus_action_available``,
      ``reaction_available``, ``movement_remaining``, ``attacks_remaining``
      and the per-turn flags.
    - **The battlefield.** ``grid`` and ``positions`` (cell ids).
    - **Hit points.** ``hp`` and ``temp_hp`` per creature, ``dead`` and
      ``deaths``.
    - **Effects.** ``effects`` (every active effect, per target),
      ``effect_conditions``, ``conditions``, ``concentration`` (each caster's
      effects), ``concentration_rounds_remaining``, ``repeat_saves``, and the
      one-turn riders (``help_grants``, ``vex_grants``, ``sap_marks``,
      ``slow_marks``, ``hidden``, ``rage_bonus_extensions``,
      ``reaction_effects_pending_expiry``).
    - **Readied actions.** ``readied``.
    - **Resources.** Spell slots, Pact Magic slots, spells, feature and item
      counters, ``expended_resources``.
    - **Monsters.** ``monster_action_uses`` (spent recharge, per-day uses),
      ``legendary_windows_used``, ``legendary_resistance_armed``,
      ``last_ended_turn``, ``monster_turn_start_done``.
    - **Conjurations.** ``constructs``, ``transforms``, ``summons``,
      ``summon_counts``.
    - **Lingering spells.** ``lingering_spells``: casts whose later
      activities still wait for their triggers (``dnd5e_engine.lingering``).
    - **The turn in progress.** ``turn_events``.
    """

    version: Literal[1] = STATE_VERSION
    combat_id: str
    session_id: str
    location: str
    grid: GridScene

    round: int
    turn_index: int
    active_combatant: str | None
    ended: bool = False
    outcome: CombatOutcome | None = None

    combatants: list[Combatant]
    party: list[str]
    encounter: list[str]
    positions: dict[str, str]
    hp: dict[str, int]
    temp_hp: dict[str, int] = Field(default_factory=dict)
    dead: list[str] = Field(default_factory=list)
    deaths: list[DeathRecord] = Field(default_factory=list)

    conditions: dict[str, list[str]] = Field(default_factory=dict)
    effects: dict[str, list[ActiveEffect]] = Field(default_factory=dict)
    effect_conditions: list[EffectConditions] = Field(default_factory=list)
    concentration: dict[str, list[EffectKey]] = Field(default_factory=dict)
    concentration_rounds_remaining: dict[str, int] = Field(default_factory=dict)
    repeat_saves: list[RepeatSaves] = Field(default_factory=list)
    reaction_effects_pending_expiry: dict[str, list[EffectKey]] = Field(default_factory=dict)
    help_grants: dict[str, list[str]] = Field(default_factory=dict)
    hidden: list[str] = Field(default_factory=list)
    vex_grants: dict[str, dict[str, int]] = Field(default_factory=dict)
    rage_bonus_extensions: list[str] = Field(default_factory=list)
    sap_marks: dict[str, str] = Field(default_factory=dict)
    slow_marks: dict[str, list[str]] = Field(default_factory=dict)
    undead_fortitude_holds: dict[str, bool] = Field(default_factory=dict)

    readied: list[ReadiedReaction] = Field(default_factory=list)

    spell_slots: dict[str, dict[int, int]] = Field(default_factory=dict)
    pact_slots: dict[str, dict[int, int]] = Field(default_factory=dict)
    spells_known: dict[str, list[str]] = Field(default_factory=dict)
    custom_counters: dict[str, dict[str, dict[str, int]]] = Field(default_factory=dict)
    expended_resources: dict[str, dict[str, int]] = Field(default_factory=dict)
    opportunity_attack_weapons: dict[str, str] = Field(default_factory=dict)

    monster_slugs: dict[str, str] = Field(default_factory=dict)
    xp_values: dict[str, int] = Field(default_factory=dict)
    monster_action_uses: dict[str, dict[str, MonsterActionUsesState]] = Field(default_factory=dict)
    monster_turn_start_done: TurnKey | None = None
    last_ended_turn: TurnKey | None = None
    legendary_windows_used: list[LegendaryWindow] = Field(default_factory=list)
    legendary_resistance_armed: dict[str, int] = Field(default_factory=dict)
    legendary_resistance_applied: list[int] = Field(default_factory=list)

    constructs: dict[str, ConstructState] = Field(default_factory=dict)
    transforms: dict[str, TransformState] = Field(default_factory=dict)
    summons: dict[str, SummonState] = Field(default_factory=dict)
    summon_counts: dict[str, int] = Field(default_factory=dict)
    departed_actor_id: str | None = None

    lingering_spells: list[LingeringSpell] = Field(default_factory=list)

    turn_events: list[CombatEvent] = Field(default_factory=list)

    def combatant(self, entity_id: str) -> Combatant | None:
        """The combatant ``entity_id`` names, or ``None``."""
        return next((c for c in self.combatants if c.entity_id == entity_id), None)

    async def start_turn(self, seed: int) -> CombatStep:
        """Start the current turn with full lifecycle: TurnStarted event,
        turn_start hooks, and pending death save roll.

        This creates a fresh ``_LiveCombat`` from the state, runs the turn-start
        lifecycle (same as ``_begin_turn`` with ``new_round=False``), and returns
        the events and new state.

        ``seed`` draws every die for the turn-start events (e.g., death save).
        """
        live = _live_from_state(self, random.Random(seed))
        events = _capture(live)
        _begin_turn(live, new_round=False)
        return _step(live, events)

    def at_turn(self, round_number: int, active_combatant: str) -> CombatState:
        """This state with the turn moved to ``active_combatant`` in
        ``round_number``, for a host whose record names the round and the
        active combatant: the turn opens as if it had just started, with the
        combatant's turn resources as this state holds them. ``turn_events``
        restarts at that ``TurnStarted``.

        Note: This method creates a state with the turn pointer updated but
        does not emit turn-start events. Use ``start_turn`` on a fresh state
        (or ``load_combat`` + handle API) when you need the full turn-start
        lifecycle (events, hooks, death save). This method is for hosts that
        track turn state independently and only need the CombatState updated.
        """
        index = next(
            (i for i, c in enumerate(self.combatants) if c.entity_id == active_combatant), None
        )
        if index is None:
            raise ValueError(f"at_turn: {active_combatant!r} is not in the initiative order")
        return self.model_copy(
            update={
                "round": round_number,
                "turn_index": index,
                "active_combatant": active_combatant,
                "turn_events": [TurnStarted(actor_id=active_combatant)],
            }
        )


async def start_turn(state: CombatState, seed: int) -> CombatStep:
    """Start the current turn on ``state`` with full lifecycle.

    This is a convenience wrapper around ``CombatState.start_turn`` that
    allows using ``start_turn`` as a standalone function instead of a method.
    It creates a fresh ``_LiveCombat`` from the state, runs the turn-start
    lifecycle (same as ``_begin_turn`` with ``new_round=False``), and returns
    the events and new state.

    ``seed`` draws every die for the turn-start events (e.g., death save).
    """
    return await state.start_turn(seed)


class CombatCall(_Model):
    """One resolving call, as a continuation replays it: a player intent
    (``kind="intent"``) or a monster turn or legendary action
    (``kind="monster_turn"``)."""

    kind: Literal["intent", "monster_turn"]
    actor_id: str | None = None
    intent: PlayerIntent | None = None
    legendary: bool = False


class Continuation(_Model):
    """Everything ``resume`` needs to finish a suspended call, as plain JSON:
    the call, its seed, every reaction answer it took before the pause, and the
    digest of the state it started from (``state_digest``)."""

    version: Literal[1] = 1
    call: CombatCall
    seed: int
    choices: list[ReactionChoice] = Field(default_factory=list)
    state_digest: str


class CombatSuspension(_Model):
    """A call paused at a reaction's trigger because the policy answered
    ``"suspend"``: the prompt to put to the player, and the continuation."""

    prompt: ReactionPrompt
    continuation: Continuation


class CombatStep(_Model):
    """What a resolving call returns: the events it emitted, in order, and the
    combat's state after them.

    When the call paused for a reaction, ``suspension`` holds the pause;
    ``state`` is then the state the call started from, unchanged, and
    ``events`` are the events up to the trigger, for display only: the
    finished resolution ``resume`` returns emits them again."""

    events: list[CombatEvent]
    state: CombatState
    suspension: CombatSuspension | None = None


class EndCombatStep(_Model):
    """What ``close_combat`` returns."""

    outcome: CombatOutcome
    events: list[CombatEvent]
    final_active_effects: list[ActiveEffect]
    state: CombatState


# ── live <-> state ──────────────────────────────────────────────────────────


def _turn_tail_start(log: Sequence[CombatEvent]) -> int:
    """Index of the latest ``TurnStarted``: where the turn in progress began."""
    for index in range(len(log) - 1, -1, -1):
        if isinstance(log[index], TurnStarted):
            return index
    return 0


def _uses_state(uses: MonsterActionUses) -> MonsterActionUsesState:
    return MonsterActionUsesState(
        recharge_spent=uses.recharge_spent, uses_remaining=dict(uses.uses_remaining)
    )


def _uses_live(uses: MonsterActionUsesState) -> MonsterActionUses:
    return MonsterActionUses(
        recharge_spent=uses.recharge_spent, uses_remaining=dict(uses.uses_remaining)
    )


def _field_adapter(name: str) -> TypeAdapter[Any]:
    return TypeAdapter(Combatant.model_fields[name].annotation)


def _stash_state(stash: dict[str, Any]) -> dict[str, Any]:
    return {
        name: _field_adapter(name).dump_python(value, mode="json") for name, value in stash.items()
    }


def _stash_live(stash: dict[str, Any]) -> dict[str, Any]:
    return {name: _field_adapter(name).validate_python(value) for name, value in stash.items()}


def _state_from_live(live: _LiveCombat) -> CombatState:
    """The lossless state of ``live`` (see the module docstring for what is
    left out and why)."""
    if live.grid_scene is None:
        raise ValueError("combat_state: this combat was built without a grid scene")
    tail = _turn_tail_start(live.event_log)
    return CombatState.model_validate(
        {
            "combat_id": live.handle_id,
            "session_id": live.session_id,
            "location": live.scene_location_id,
            "grid": live.grid_scene.model_copy(update={"sunlight": live.scene_sunlight}),
            "round": live.round_number,
            "turn_index": live.current_turn_index,
            "active_combatant": live.current_actor_id,
            "ended": live.ended,
            "outcome": live.final_outcome,
            "combatants": [c.model_copy(deep=True) for c in live.initiative],
            "party": sorted(live.party_ids),
            "encounter": sorted(live.encounter_ids),
            "positions": dict(live.actor_zone),
            "hp": dict(live.tracked_hp),
            "temp_hp": dict(live.tracked_temp_hp),
            "dead": sorted(live.dead_ids),
            "deaths": list(live.deaths_recorded),
            "conditions": {k: sorted(v) for k, v in live.active_conditions.items()},
            "effects": {
                k: [e.model_copy(deep=True) for e in v] for k, v in live.active_effects.items()
            },
            "effect_conditions": [
                {"effect": EffectKey.of(k), "conditions": list(v)}
                for k, v in live.conditions_by_effect.items()
            ],
            "concentration": {
                k: [EffectKey.of(i) for i in v] for k, v in live.concentration_chain.items()
            },
            "concentration_rounds_remaining": dict(live.concentration_rounds_remaining),
            "repeat_saves": [
                {"effect": EffectKey.of(k), "saves": [RepeatSave(**s) for s in v]}
                for k, v in live.repeat_save_on_turn_end.items()
            ],
            "reaction_effects_pending_expiry": {
                k: [EffectKey.of(i) for i in v]
                for k, v in live.reaction_effects_pending_expiry.items()
            },
            "help_grants": {k: list(v) for k, v in live.help_grants.items()},
            "hidden": sorted(live.hidden_entities),
            "vex_grants": {k: dict(v) for k, v in live.vex_grants.items()},
            "rage_bonus_extensions": sorted(live.rage_bonus_extensions),
            "sap_marks": dict(live.sap_marks),
            "slow_marks": {k: sorted(v) for k, v in live.slow_marks.items()},
            "undead_fortitude_holds": dict(live.undead_fortitude_holds),
            "readied": [
                ReadiedReaction(
                    owner_id=r.owner_id,
                    trigger=r.trigger,
                    spell_id=r.spell_id,
                    slot_level=r.slot_level,
                )
                for r in live.pending_reactions
            ],
            "spell_slots": {k: dict(v) for k, v in live.spell_slots_by_entity.items()},
            "pact_slots": {k: dict(v) for k, v in live.pact_slots_by_entity.items()},
            "spells_known": {k: list(v) for k, v in live.spells_known_by_entity.items()},
            "custom_counters": {
                k: {key: dict(c) for key, c in v.items()}
                for k, v in live.custom_counters_by_entity.items()
            },
            "expended_resources": {k: dict(v) for k, v in live.expended_resources.items()},
            "opportunity_attack_weapons": dict(live.opportunity_attack_weapons),
            "monster_slugs": dict(live.monster_slug_by_entity),
            "xp_values": dict(live.xp_value_by_entity),
            "monster_action_uses": {
                k: {slug: _uses_state(u) for slug, u in v.items()}
                for k, v in live.monster_action_uses_by_entity.items()
            },
            "monster_turn_start_done": (
                None
                if live.monster_turn_start_done is None
                else TurnKey(
                    round=live.monster_turn_start_done[0], actor_id=live.monster_turn_start_done[1]
                )
            ),
            "last_ended_turn": (
                None
                if live.last_ended_turn is None
                else TurnKey(round=live.last_ended_turn[0], actor_id=live.last_ended_turn[1])
            ),
            "legendary_windows_used": [
                LegendaryWindow(round=r, ended_actor_id=a, monster_id=m)
                for r, a, m in sorted(live.legendary_windows_used)
            ],
            "legendary_resistance_armed": dict(live.legendary_resistance_armed),
            "legendary_resistance_applied": sorted(
                i - tail for i in live.legendary_resistance_applied_event_indices if i >= tail
            ),
            "constructs": {
                k: ConstructState(
                    construct_id=c.construct_id,
                    owner_id=c.owner_id,
                    spell_id=c.spell_id,
                    cell=c.cell,
                    slot_level=c.slot_level,
                    anchor=EffectKey.of(c.anchor),
                    cast_round=c.cast_round,
                )
                for k, c in live.constructs.items()
            },
            "transforms": {
                k: TransformState(
                    entity_id=t.entity_id,
                    form_slug=t.form_slug,
                    source=t.source,
                    effect_id=t.effect_id,
                    origin=t.origin,
                    stash=_stash_state(t.stash),
                    original_monster_slug=t.original_monster_slug,
                    original_action_uses=(
                        None
                        if t.original_action_uses is None
                        else {slug: _uses_state(u) for slug, u in t.original_action_uses.items()}
                    ),
                    form_proficiency_bonus=t.form_proficiency_bonus,
                    attacks_per_action=t.attacks_per_action,
                    clears_temp_hp_on_end=t.clears_temp_hp_on_end,
                )
                for k, t in live.transforms.items()
            },
            "summons": {
                k: SummonState(
                    entity_id=s.entity_id,
                    owner_id=s.owner_id,
                    spell_id=s.spell_id,
                    stat_block_slug=s.stat_block_slug,
                    slot_level=s.slot_level,
                    anchor=EffectKey.of(s.anchor),
                    magnitudes=SummonMagnitudes(
                        ability_scores=dict(s.magnitudes.ability_scores),
                        proficiency_bonus=s.magnitudes.proficiency_bonus,
                        attack_bonus=s.magnitudes.attack_bonus,
                        attack_damage_bonus=s.magnitudes.attack_damage_bonus,
                    ),
                    attacks_per_action=s.attacks_per_action,
                )
                for k, s in live.summons.items()
            },
            "summon_counts": dict(live.summon_counts),
            "departed_actor_id": live.departed_actor_id,
            "lingering_spells": [s.model_copy(deep=True) for s in live.lingering_spells],
            # Through JSON, so the state shares no object with the live combat.
            "turn_events": _EVENTS.validate_json(_EVENTS.dump_json(live.event_log[tail:])),
        }
    )


def _live_from_state(state: CombatState, rng: random.Random) -> _LiveCombat:
    """A fresh ``_LiveCombat`` holding ``state``, drawing from ``rng``."""
    # Every container is rebuilt from a deep copy, so the combat never shares
    # a mutable object with the (frozen) state it came from.
    state = CombatState.model_validate_json(state.model_dump_json())
    live = _LiveCombat(
        handle_id=state.combat_id,
        session_id=state.session_id,
        initiative=list(state.combatants),
        party_ids=set(state.party),
        encounter_ids=set(state.encounter),
        topology=GridTopology(state.grid),
        rng=rng,
        event_queue=asyncio.Queue(),
        scene_location_id=state.location,
        scene_sunlight=state.grid.sunlight,
        current_turn_index=state.turn_index,
        round_number=state.round,
        ended=state.ended,
        final_outcome=state.outcome,
        actor_zone=dict(state.positions),
        opportunity_attack_weapons=dict(state.opportunity_attack_weapons),
        monster_slug_by_entity=dict(state.monster_slugs),
        xp_value_by_entity=dict(state.xp_values),
        event_log=list(state.turn_events),
        tracked_hp=dict(state.hp),
        tracked_temp_hp=dict(state.temp_hp),
        undead_fortitude_holds=dict(state.undead_fortitude_holds),
        active_conditions={k: set(v) for k, v in state.conditions.items()},
        active_effects={k: list(v) for k, v in state.effects.items()},
        deaths_recorded=list(state.deaths),
        dead_ids=set(state.dead),
        expended_resources={k: dict(v) for k, v in state.expended_resources.items()},
        current_actor_id=state.active_combatant,
        spell_slots_by_entity={k: dict(v) for k, v in state.spell_slots.items()},
        pact_slots_by_entity={k: dict(v) for k, v in state.pact_slots.items()},
        spells_known_by_entity={k: list(v) for k, v in state.spells_known.items()},
        custom_counters_by_entity={
            k: {key: dict(c) for key, c in v.items()} for k, v in state.custom_counters.items()
        },
        concentration_chain={k: [i.key() for i in v] for k, v in state.concentration.items()},
        concentration_rounds_remaining=dict(state.concentration_rounds_remaining),
        conditions_by_effect={e.effect.key(): list(e.conditions) for e in state.effect_conditions},
        repeat_save_on_turn_end={
            r.effect.key(): [s.model_dump(exclude_none=True) for s in r.saves]
            for r in state.repeat_saves
        },
        pending_reactions=[
            _PendingReaction(
                owner_id=r.owner_id, trigger=r.trigger, spell_id=r.spell_id, slot_level=r.slot_level
            )
            for r in state.readied
        ],
        reaction_effects_pending_expiry={
            k: [i.key() for i in v] for k, v in state.reaction_effects_pending_expiry.items()
        },
        help_grants={k: list(v) for k, v in state.help_grants.items()},
        hidden_entities=set(state.hidden),
        vex_grants={k: dict(v) for k, v in state.vex_grants.items()},
        rage_bonus_extensions=set(state.rage_bonus_extensions),
        sap_marks=dict(state.sap_marks),
        slow_marks={k: set(v) for k, v in state.slow_marks.items()},
        monster_action_uses_by_entity={
            k: {slug: _uses_live(u) for slug, u in v.items()}
            for k, v in state.monster_action_uses.items()
        },
        monster_turn_start_done=(
            None
            if state.monster_turn_start_done is None
            else (state.monster_turn_start_done.round, state.monster_turn_start_done.actor_id)
        ),
        last_ended_turn=(
            None
            if state.last_ended_turn is None
            else (state.last_ended_turn.round, state.last_ended_turn.actor_id)
        ),
        departed_actor_id=state.departed_actor_id,
        legendary_windows_used={
            (w.round, w.ended_actor_id, w.monster_id) for w in state.legendary_windows_used
        },
        legendary_resistance_armed=dict(state.legendary_resistance_armed),
        legendary_resistance_applied_event_indices=set(state.legendary_resistance_applied),
        constructs={
            k: _Construct(
                construct_id=c.construct_id,
                owner_id=c.owner_id,
                spell_id=c.spell_id,
                cell=c.cell,
                slot_level=c.slot_level,
                anchor=c.anchor.key(),
                cast_round=c.cast_round,
            )
            for k, c in state.constructs.items()
        },
        transforms={
            k: _Transform(
                entity_id=t.entity_id,
                form_slug=t.form_slug,
                source=t.source,
                effect_id=t.effect_id,
                origin=t.origin,
                stash=_stash_live(t.stash),
                original_monster_slug=t.original_monster_slug,
                original_action_uses=(
                    None
                    if t.original_action_uses is None
                    else {slug: _uses_live(u) for slug, u in t.original_action_uses.items()}
                ),
                form_proficiency_bonus=t.form_proficiency_bonus,
                attacks_per_action=t.attacks_per_action,
                clears_temp_hp_on_end=t.clears_temp_hp_on_end,
            )
            for k, t in state.transforms.items()
        },
        summons={
            k: _Summon(
                entity_id=s.entity_id,
                owner_id=s.owner_id,
                spell_id=s.spell_id,
                stat_block_slug=s.stat_block_slug,
                slot_level=s.slot_level,
                anchor=s.anchor.key(),
                magnitudes=StatBlockMagnitudes(
                    ability_scores=dict(s.magnitudes.ability_scores),
                    proficiency_bonus=s.magnitudes.proficiency_bonus,
                    attack_bonus=s.magnitudes.attack_bonus,
                    attack_damage_bonus=s.magnitudes.attack_damage_bonus,
                ),
                attacks_per_action=s.attacks_per_action,
            )
            for k, s in state.summons.items()
        },
        summon_counts=dict(state.summon_counts),
        lingering_spells=[s.model_copy(deep=True) for s in state.lingering_spells],
        grid_scene=state.grid,
    )
    _register_default_turn_hooks(live)
    return live


# ── stateless calls ─────────────────────────────────────────────────────────


def _capture(live: _LiveCombat) -> list[CombatEvent]:
    events: list[CombatEvent] = []
    live.event_listeners.append(events.append)
    return events


def _step(live: _LiveCombat, events: list[CombatEvent]) -> CombatStep:
    live.event_listeners.remove(events.append)
    return CombatStep(
        events=_EVENTS.validate_json(_EVENTS.dump_json(events)), state=_state_from_live(live)
    )


async def begin_combat(
    *,
    session_id: str,
    party: list[PartyMemberSpec],
    encounter: list[EncounterMemberSpec],
    grid_scene: GridScene,
    seed: int,
    scene_location_id: str = "loc:unknown",
    active_effects: Sequence[ActiveEffect] = (),
) -> CombatStep:
    """Open a combat, as ``start_combat`` does, and return its first state
    instead of a handle. ``seed`` draws the Initiative rolls of every member
    whose ``initiative`` is ``None``. ``combat_id`` is
    ``combat:<session_id>:<seed>``, as ``start_combat`` names its handle."""
    live, events = _open_combat(
        session_id=session_id,
        party=party,
        encounter=encounter,
        grid_scene=grid_scene,
        rng=random.Random(seed),
        handle_id=f"combat:{session_id}:{seed:08x}",
        scene_location_id=scene_location_id,
        active_effects=active_effects,
    )
    return CombatStep(
        events=_EVENTS.validate_json(_EVENTS.dump_json(events)), state=_state_from_live(live)
    )


#: Where ``cast_outside_combat`` seats the creatures it is not given cells for:
#: the caster in the middle, the others in the ring around it. Every creature
#: is within 5 feet of the caster (touch range) up to eight others, and within
#: 10 feet up to sixteen.
_SCENE_OFFSETS: Final = (
    (0, 0),
    (1, 0),
    (0, 1),
    (-1, 0),
    (0, -1),
    (1, 1),
    (-1, 1),
    (-1, -1),
    (1, -1),
)


async def cast_outside_combat(
    *,
    session_id: str,
    caster_id: str,
    intent: PlayerIntent,
    party: list[PartyMemberSpec],
    others: list[EncounterMemberSpec] | None = None,
    grid_scene: GridScene | None = None,
    seed: int,
    scene_location_id: str = "loc:unknown",
    active_effects: Sequence[ActiveEffect] = (),
) -> CombatStep:
    """Resolve one ``cast_spell`` declared in a narrative turn, outside combat
    (contract 03, "Who may declare what"), and return its events and the
    state the cast leaves.

    SRD 5.2.1 "Casting Time": a spell takes as long as its casting time says,
    in or out of a fight; outside one, a minute-long or hour-long spell is
    cast like any other. Everything else is the on-turn cast: the slot or
    slotless cast it spends, the concentration it begins and ends, its attack
    or save, its damage and its effects, resolved by the same code with the
    same dice. No initiative is rolled, no turn passes, no Action is spent
    (``CombatState.round`` stays 1 and the caster's turn stays open), so
    ``CombatState.effects``, ``concentration``, ``lingering_spells`` and the
    resource fields are what the host stores.

    ``party`` holds the caster and the creatures that are on its side;
    ``others`` the creatures that are not (a bandit, a door's guardian). The
    spell reaches who ``intent`` names, or its area catches. With no
    ``grid_scene`` the creatures are seated around the caster
    (``_SCENE_OFFSETS``), so range and line of sight never refuse a cast;
    with one, each ``zone_id`` is its cell (the spec requires one either way,
    and ignores it without a scene). Raises ``ValueError`` when
    ``caster_id`` is not in ``party`` or ``intent`` is not a ``cast_spell``.
    """
    if intent.intent_type != "cast_spell":
        raise ValueError("cast_outside_combat: only a cast_spell resolves outside combat")
    if all(member.entity_id != caster_id for member in party):
        raise ValueError(f"cast_outside_combat: {caster_id!r} is not in the party")
    others = list(others or [])
    seated = grid_scene
    if seated is None:
        seated = GridScene(width=7, height=7)
        ids = [caster_id, *(m.entity_id for m in party if m.entity_id != caster_id)]
        ids += [e.entity_id for e in others]
        cells = _scene_cells(len(ids))
        cell_of = dict(zip(ids, cells, strict=True))
        party = [m.model_copy(update={"zone_id": cell_of[m.entity_id]}) for m in party]
        others = [e.model_copy(update={"zone_id": cell_of[e.entity_id]}) for e in others]
    # The caster goes first and nobody rolls: a fixed count draws no dice.
    party = [
        m.model_copy(update={"initiative": 10_000 if m.entity_id == caster_id else 0})
        for m in party
    ]
    others = [e.model_copy(update={"initiative": 0}) for e in others]
    live, _opened = _open_combat(
        session_id=session_id,
        party=party,
        encounter=others,
        grid_scene=seated,
        rng=random.Random(seed),
        handle_id=f"narrative:{session_id}:{seed:08x}",
        scene_location_id=scene_location_id,
        active_effects=active_effects,
        allow_empty_encounter=True,
    )
    live.narrative = True
    events = _capture(live)
    await _submit_player_intent(live, caster_id, intent)
    return _step(live, events)


def _scene_cells(count: int) -> list[str]:
    """``count`` cell ids around ``(3, 3)``, nearest first (``_SCENE_OFFSETS``,
    then the next ring)."""
    offsets = list(_SCENE_OFFSETS)
    ring = [(dx, dy) for dx in range(-2, 3) for dy in range(-2, 3) if max(abs(dx), abs(dy)) == 2]
    offsets += ring
    if count > len(offsets):
        raise ValueError(f"cast_outside_combat seats at most {len(offsets)} creatures")
    return [f"{3 + dx},{3 + dy}" for dx, dy in offsets[:count]]


def state_digest(state: CombatState) -> str:
    """SHA-256 of the state's canonical JSON (sorted keys, no whitespace), as
    lowercase hex: contract 03's ``state_digest``, for a ``CombatState``."""
    canonical = json.dumps(state.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


async def _run_call(
    state: CombatState,
    call: CombatCall,
    seed: int,
    *,
    choices: Sequence[ReactionChoice] = (),
    reactions: ReactionPolicy | None = None,
) -> CombatStep:
    """Run ``call`` against a fresh combat built from ``state``, answering its
    reaction prompts from ``choices`` first, then from ``reactions``."""
    live = _live_from_state(state, random.Random(seed))
    live.reaction_policy = reactions
    live.reaction_replay = list(choices)
    events = _capture(live)
    try:
        if call.kind == "intent":
            if call.actor_id is None or call.intent is None:
                raise ValueError("an intent call names its actor and its intent")
            await _submit_player_intent(live, call.actor_id, call.intent)
        else:
            await _advance_monster_turn(live, legendary=call.legendary, actor_id=call.actor_id)
    except ReactionSuspended as paused:
        live.event_listeners.remove(events.append)
        return CombatStep(
            events=_EVENTS.validate_json(_EVENTS.dump_json(events)),
            state=state,
            suspension=CombatSuspension(
                prompt=paused.prompt,
                continuation=Continuation(
                    call=call,
                    seed=seed,
                    choices=list(live.reaction_record),
                    state_digest=state_digest(state),
                ),
            ),
        )
    if live.reaction_replay:
        raise RuntimeError("resume replay finished before reaching every recorded reaction")
    return _step(live, events)


async def resolve_intent(
    state: CombatState,
    *,
    actor_id: str,
    intent: PlayerIntent,
    seed: int,
    reactions: ReactionPolicy | None = None,
) -> CombatStep:
    """Resolve one player intent against ``state``, drawing every die from
    ``random.Random(seed)``: ``submit_player_intent`` without a handle. Raises
    ``IntentRejectedError`` exactly as it does; ``state`` itself is never
    changed, so a rejected intent leaves the caller's state as it was.

    ``reactions`` answers each reaction the resolution offers
    (``reactions.py``); ``None`` is ``default_reaction_policy``. A
    ``"suspend"`` answer returns a step whose ``suspension`` is set."""
    call = CombatCall(kind="intent", actor_id=actor_id, intent=intent)
    return await _run_call(state, call, seed, reactions=reactions)


async def resolve_monster_turn(
    state: CombatState,
    *,
    seed: int,
    legendary: bool = False,
    actor_id: str | None = None,
    reactions: ReactionPolicy | None = None,
) -> CombatStep:
    """Play the current monster's turn, or with ``legendary=True`` one
    legendary action, against ``state``: ``advance_monster_turn`` without a
    handle, drawing every die from ``random.Random(seed)``. ``reactions`` as
    for ``resolve_intent``."""
    call = CombatCall(kind="monster_turn", actor_id=actor_id, legendary=legendary)
    return await _run_call(state, call, seed, reactions=reactions)


async def resume(
    state: CombatState,
    suspension: CombatSuspension,
    decision: ReactionDecision,
    seed: int,
    *,
    reactions: ReactionPolicy | None = None,
) -> CombatStep:
    """Finish a suspended call with the player's ``decision``: the whole
    resolution, from its start, as the host commits it (contract 03,
    "Reactions").

    ``state`` must be the state the call started from: when its digest differs
    from the continuation's, nothing resolves and this raises
    ``IntentRejectedError("state_changed", ...)``. The call is replayed from
    that state and its own seed, its earlier reaction prompts answered as they
    were, up to the paused one, which takes ``decision``; every die after it
    comes from ``seed``. The step holds every event of the whole call. A later
    prompt is answered by ``reactions`` and can suspend again."""
    continuation = suspension.continuation
    if state_digest(state) != continuation.state_digest:
        raise IntentRejectedError(
            "state_changed", "the combat state is not the one the suspended call started from"
        )
    prompt = suspension.prompt
    answered = ReactionChoice(
        reactor_id=prompt.reactor_id,
        reaction_key=prompt.reaction_key,
        decision=decision,
        seed=seed,
    )
    return await _run_call(
        state,
        continuation.call,
        continuation.seed,
        choices=[*continuation.choices, answered],
        reactions=reactions,
    )


def arm_legendary_resistance(state: CombatState, entity_id: str) -> CombatStep:
    """Arm one Legendary Resistance use, as ``resolve_legendary_resistance``
    does. It rolls nothing, so it takes no seed and emits no event."""
    live = _live_from_state(state, random.Random(0))
    events = _capture(live)
    _arm_legendary_resistance(live, entity_id)
    return _step(live, events)


async def close_combat(state: CombatState) -> EndCombatStep:
    """End the combat, as ``end_combat`` does: the outcome, the closing
    events, the effects still active, and the ended state. Rolls nothing."""
    live = _live_from_state(state, random.Random(0))
    events = _capture(live)
    result = _close_combat(live)
    step = _step(live, events)
    return EndCombatStep(
        outcome=result.outcome,
        events=step.events,
        final_active_effects=list(result.final_active_effects),
        state=step.state,
    )


# ── handle bridge ───────────────────────────────────────────────────────────


def load_combat(state: CombatState, *, rng_seed: int = 0) -> CombatHandle:
    """Put ``state`` in this process's registry and return its handle, so the
    handle API (``submit_player_intent`` and the rest) can drive it. The
    handle's id is ``state.combat_id``; a combat already registered under it
    is replaced. Calls without their own ``seed`` draw from
    ``random.Random(rng_seed)``."""
    live = _live_from_state(state, random.Random(rng_seed))
    _REGISTRY[live.handle_id] = live
    return CombatHandle(handle_id=live.handle_id)


def combat_state_of(handle: CombatHandle) -> CombatState:
    """The ``CombatState`` of the combat ``handle`` names. Events the host has
    not drained yet are not part of it."""
    return _state_from_live(_get_live(handle))
