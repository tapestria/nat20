"""Stateless replay core — the demo's whole state model.

The demo holds no server-side combat state. A fight is a :class:`FightLog`
(scenario id + rng seed + the ordered list of commands the player issued);
every render replays that log from scratch against a freshly opened combat
and throws the live handle away again. Two guarantees make that sound:

* the engine is deterministic under a fixed ``rng_seed`` and a fixed intent
  sequence, so replaying the same log twice yields the same event stream;
* replaying a prefix of a log yields a prefix of the full log's event
  stream, so the UI can render "what is new" as a delta without ever
  diffing state.

``tests/test_replay.py`` is the executable proof of both properties.

Only top-level ``dnd5e_engine`` names are imported here — the demo treats
the engine's ``__all__`` as its entire contract.
"""

from __future__ import annotations

import base64
import binascii
import contextlib
import uuid
from dataclasses import dataclass
from typing import Annotated, Literal

from dnd5e_engine import (
    CombatEvent,
    CombatHandle,
    CombatOutcome,
    EncounterMemberSpec,
    GridScene,
    IntentRejectedError,
    LiveCombatView,
    PartyMemberSpec,
    PlayerIntent,
    advance_monster_turn,
    drain_pending_events,
    end_combat,
    get_live,
    start_combat,
    submit_player_intent,
)
from pydantic import BaseModel, ConfigDict, Field, ValidationError

__all__ = [
    "MAX_COMMANDS",
    "Command",
    "FightLog",
    "IntentCommand",
    "LogTooLargeError",
    "MonsterTurnCommand",
    "ReplayOutcome",
    "decode_log",
    "encode_log",
    "replay_fight",
]

# Hard cap on log length: a replay is O(len(commands)) engine work per
# request, so an unbounded log in a URL is a trivial DoS vector.
MAX_COMMANDS: int = 500


class IntentCommand(BaseModel):
    """A PC intent submitted on that PC's turn."""

    model_config = ConfigDict(extra="forbid")

    t: Literal["intent"] = "intent"
    actor: str
    intent: PlayerIntent


class MonsterTurnCommand(BaseModel):
    """Advance the engine through one monster turn."""

    model_config = ConfigDict(extra="forbid")

    t: Literal["monster_turn"] = "monster_turn"


Command = Annotated[IntentCommand | MonsterTurnCommand, Field(discriminator="t")]


class FightLog(BaseModel):
    """The complete, self-contained state of a demo fight."""

    model_config = ConfigDict(extra="forbid")

    v: Literal[1] = 1
    scenario_id: str
    seed: int
    commands: list[Command] = Field(default_factory=list)


class LogTooLargeError(Exception):
    """Raised when a log exceeds :data:`MAX_COMMANDS`."""


@dataclass(frozen=True)
class ReplayOutcome:
    """Everything a renderer needs from one replay.

    ``view`` is snapshotted *before* ``end_combat`` tears the live combat
    down, so it still reflects the final in-combat state.
    """

    view: LiveCombatView
    all_events: list[CombatEvent]
    delta_events: list[CombatEvent]
    accepted: int
    rejected_reason: str | None
    is_over: bool
    outcome: CombatOutcome | None


def _is_over(view: LiveCombatView) -> bool:
    """All foes down or the whole party down."""
    return (view.encounter_ids <= view.dead_ids) or (view.party_ids <= view.dead_ids)


async def replay_fight(
    log: FightLog,
    party: list[PartyMemberSpec],
    encounter: list[EncounterMemberSpec],
    grid: GridScene,
) -> ReplayOutcome:
    """Replay ``log`` from scratch and return the resulting stream + snapshot.

    Specs are passed in (rather than looked up by ``log.scenario_id``) so
    this module stays independent of the scenario catalog. Callers must
    hand over freshly constructed spec models on every call — the engine
    projects them into live combatants and must never see shared state.
    """
    if len(log.commands) > MAX_COMMANDS:
        raise LogTooLargeError(f"{len(log.commands)} commands > cap {MAX_COMMANDS}")

    start = await start_combat(
        session_id=f"demo:{uuid.uuid4().hex}",
        party=party,
        encounter=encounter,
        grid_scene=grid,
        rng_seed=log.seed,
    )
    handle: CombatHandle = start.handle
    try:
        all_events: list[CombatEvent] = list(start.events)
        # start_combat both returns the open events and leaves them queued for
        # narration consumers; drop that copy so the first command's drain does
        # not replay them a second time.
        drain_pending_events(handle)
        # Index into all_events where the last applied command's events begin;
        # 0 means "the open events are the delta" (empty log).
        delta_start = 0
        accepted = 0
        rejected_reason: str | None = None

        for cmd in log.commands:
            marker = len(all_events)
            try:
                if isinstance(cmd, IntentCommand):
                    await submit_player_intent(handle, actor_id=cmd.actor, intent=cmd.intent)
                else:
                    await advance_monster_turn(handle)
            except IntentRejectedError as exc:
                all_events.extend(drain_pending_events(handle))
                rejected_reason = f"{exc.reason}: {exc.detail}"
                break
            all_events.extend(drain_pending_events(handle))
            delta_start = marker
            accepted += 1
            if _is_over(get_live(handle)):
                # Any remaining commands are unreachable. A well-formed client
                # never sends them; if present they are simply not applied and
                # `rejected_reason` stays None.
                break

        view = get_live(handle)
        is_over = _is_over(view)
        # Always close: the registry entry must not outlive the request.
        end = await end_combat(handle)
        outcome: CombatOutcome | None = None
        if is_over:
            all_events.extend(end.events)  # CombatEnded with the real reason
            outcome = end.outcome
        return ReplayOutcome(
            view=view,
            all_events=all_events,
            delta_events=all_events[delta_start:],
            accepted=accepted,
            rejected_reason=rejected_reason,
            is_over=is_over,
            outcome=outcome,
        )
    except Exception:
        # Never leak a registry entry on an unexpected engine error.
        with contextlib.suppress(Exception):
            await end_combat(handle)
        raise


def encode_log(log: FightLog) -> str:
    """URL-safe base64 of the log's canonical JSON (the shareable fight id)."""
    return base64.urlsafe_b64encode(log.model_dump_json().encode()).decode()


def decode_log(raw: str) -> FightLog:
    """Inverse of :func:`encode_log`. Raises ``ValueError`` on any garbage."""
    try:
        payload = base64.urlsafe_b64decode(raw.encode())
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"not a valid encoded log: {exc}") from exc
    try:
        return FightLog.model_validate_json(payload)
    except ValidationError as exc:
        raise ValueError(f"not a valid fight log: {exc}") from exc
