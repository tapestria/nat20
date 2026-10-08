"""Combat lifecycle routes: start / intent / advance-monster / view / end.

Each combat is one ``CombatSession`` (``state.py``): the engine's handle, the
display names, the battlefield and the seed. ``start_combat``,
``submit_player_intent`` and ``advance_monster_turn`` queue the events they
emit on the live combat, so their routes drain that queue
(``drain_pending_events``) right after the engine call and report exactly
the events their own request produced; ``/end`` reports the events
``end_combat`` returns. A failed call leaves nothing for the next response: a
refused one (409, 422) drops what it queued, and the intent and
advance-monster routes drop whatever an engine fault (a 500) left queued
before they call the engine.

At most ``BridgeState.max_combats`` combats stay live: starting one more ends
the least recently used, and its id then answers 404.
"""

from __future__ import annotations

import dataclasses
import re
from typing import Any

from dnd5e_engine import (
    CombatEvent,
    EncounterMemberSpec,
    GridScene,
    PlayerIntent,
    advance_monster_turn,
    cell_id,
    drain_pending_events,
    end_combat,
    get_live,
    start_combat,
    submit_player_intent,
)
from dnd5e_engine.events import CombatantJoined
from dnd5e_engine.orchestrator import IntentRejectedError
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from nat20_bridge.models import PartyValidateRequest, resolve_seed, slugify
from nat20_bridge.narrate import narrate
from nat20_bridge.sheet import derive_sheet
from nat20_bridge.state import BridgeState, CombatSession

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]+")
_WHITESPACE_RE = re.compile(r"\s+")
_MAX_NAME_LEN = 80


def _sanitize_name(name: str, max_len: int = _MAX_NAME_LEN) -> str:
    """Neutralize prompt-injection vectors in combatant names.

    Homebrew monster/forge names flow verbatim into ``narrate()`` and end up
    in narration text handed to the host's LLM; a name carrying newlines,
    control characters, or an unbounded length is a prompt-injection /
    resource-exhaustion vector. Strip control characters, collapse all
    whitespace (including newlines) to single spaces, and cap length.
    """
    stripped = _CONTROL_CHARS_RE.sub(" ", name)
    collapsed = _WHITESPACE_RE.sub(" ", stripped).strip()
    return collapsed[:max_len]


class _CombatStartRequest(BaseModel):
    party: list[PartyValidateRequest]
    monsters: list[str]
    seed: int | None = None


class _IntentRequest(PlayerIntent):
    """``PlayerIntent`` plus the creature that acts. Every intent field reaches
    the engine, and an unknown key is refused (``PlayerIntent`` forbids extra
    keys) rather than silently dropped."""

    actor_id: str


def _session(state: BridgeState, cid: str) -> CombatSession:
    """The combat's session, marked as the most recently used."""
    session = state.sessions.get(cid)
    if session is None:
        raise HTTPException(status_code=404, detail=f"unknown or expired combat: {cid!r}")
    state.sessions.move_to_end(cid)
    return session


def _drain(session: CombatSession) -> list[CombatEvent]:
    """The events the last engine call queued. A creature that joined the
    fight (a summon) adds its name, so it narrates by name from then on."""
    events = drain_pending_events(session.handle)
    for event in events:
        if isinstance(event, CombatantJoined):
            session.names[event.entity_id] = _sanitize_name(event.name)
    return events


def _refused(session: CombatSession, status_code: int, detail: str) -> HTTPException:
    """The error for an engine call that refused. Whatever it queued first is
    dropped (a creature that joined still gets its name), so the next response
    reports only its own request's events."""
    _drain(session)
    return HTTPException(status_code=status_code, detail=detail)


def _envelope(
    cid: str, events: list[CombatEvent], names: dict[str, str], over: bool
) -> dict[str, Any]:
    return {
        "combat_id": cid,
        "events": [e.model_dump() for e in events],
        "narration": narrate(events, names),
        "over": over,
    }


def _build_party_specs(
    state: BridgeState, party: list[PartyValidateRequest]
) -> tuple[list[Any], dict[str, str]]:
    assert state.loader is not None
    loader = state.loader
    party_specs = []
    names: dict[str, str] = {}
    for i, member_req in enumerate(party):
        entity_id = member_req.entity_id or f"char:{slugify(member_req.name)}"
        try:
            member = derive_sheet(
                member_req.build.to_build_spec(),
                name=_sanitize_name(member_req.name),
                entity_id=entity_id,
                loader=loader,
                hp_current=member_req.hp_current,
                spells_known=member_req.spells_known,
                zone_id=cell_id(0, i),
                # The engine rolls it from the combat's own seeded generator:
                # d20 + the derived Dexterity modifier, plus Alert's bonus.
                initiative=None,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        party_specs.append(member)
        names[member.entity_id] = member.name
    return party_specs, names


def _build_encounter_specs(
    state: BridgeState, monster_slugs: list[str]
) -> tuple[list[EncounterMemberSpec], dict[str, str]]:
    assert state.loader is not None
    loader = state.loader
    encounter_specs = []
    names: dict[str, str] = {}
    for i, slug in enumerate(monster_slugs):
        monster = loader.get_monster(slug)
        if monster is None:
            raise HTTPException(status_code=404, detail=f"unknown monster: {slug!r}")
        n = i + 1
        entity_id = f"mon:{slug}-{n}"
        enc = EncounterMemberSpec(
            entity_id=entity_id,
            entity_type="Monster",
            name=_sanitize_name(f"{monster.name} {n}"),
            initiative=None,
            hp_current=monster.hp,
            hp_max=monster.hp,
            ac=monster.ac or 10,
            dexterity=monster.ability_scores.dex,
            zone_id=cell_id(1, i),
            monster_template_slug=slug,
            creature_type=str(monster.creature_type),
            damage_resistances=list(monster.damage_resistances),
            damage_immunities=list(monster.damage_immunities),
            damage_vulnerabilities=list(monster.damage_vulnerabilities),
            condition_immunities=list(monster.condition_immunities),
        )
        encounter_specs.append(enc)
        names[entity_id] = enc.name
    return encounter_specs, names


async def _evict_least_recently_used(state: BridgeState) -> None:
    """End the least recently used combats until at most ``max_combats`` are live."""
    while len(state.sessions) > state.max_combats:
        _, session = state.sessions.popitem(last=False)
        await end_combat(session.handle)


async def _start_route(state: BridgeState, req: _CombatStartRequest) -> dict[str, Any]:
    seed = resolve_seed(req.seed)
    party_specs, party_names = _build_party_specs(state, req.party)
    encounter_specs, monster_names = _build_encounter_specs(state, req.monsters)
    names = {**party_names, **monster_names}

    # Monotonic counter, not `len(state.sessions) + 1` — the latter
    # collides once any combat has ended and left `sessions` (see
    # BridgeState.next_combat_id's comment).
    cid = f"c{state.next_combat_id}"
    state.next_combat_id += 1
    grid_scene = GridScene(width=12, height=12)
    try:
        result = await start_combat(
            session_id=cid,
            party=party_specs,
            encounter=encounter_specs,
            grid_scene=grid_scene,
            rng_seed=seed,
        )
    except ValueError as exc:
        # An empty side, or more combatants than the grid has start cells.
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    session = CombatSession(handle=result.handle, names=names, grid=grid_scene, seed=seed)
    state.sessions[cid] = session
    events = _drain(session)
    await _evict_least_recently_used(state)
    return _envelope(cid, events, names, over=False)


async def _intent_route(state: BridgeState, cid: str, req: _IntentRequest) -> dict[str, Any]:
    session = _session(state, cid)
    _drain(session)  # what an engine fault (a 500) left queued belongs to no response
    intent = PlayerIntent.model_validate(req.model_dump(exclude={"actor_id"}, exclude_unset=True))
    try:
        await submit_player_intent(session.handle, req.actor_id, intent)
    except IntentRejectedError as exc:
        raise _refused(session, 409, exc.reason) from exc
    except ValueError as exc:
        # The engine can't resolve the intent as sent: an activity it has no
        # context for yet, or, partway through a move, a foe's opportunity
        # attack its stat block can't resolve (BACKLOG.md lists both). The
        # combat goes on and another intent can still resolve, so this is a
        # 422, not a 500; what the engine spent before it raised stays spent.
        raise _refused(session, 422, str(exc)) from exc
    events = _drain(session)
    return _envelope(cid, events, session.names, over=get_live(session.handle).ended)


async def _advance_monster_route(state: BridgeState, cid: str) -> dict[str, Any]:
    session = _session(state, cid)
    _drain(session)  # what an engine fault (a 500) left queued belongs to no response
    try:
        await advance_monster_turn(session.handle)
    except IntentRejectedError as exc:
        raise _refused(session, 409, exc.reason) from exc
    events = _drain(session)
    return _envelope(cid, events, session.names, over=get_live(session.handle).ended)


def _order_row(combatant: Any, names: dict[str, str], live_view: Any) -> dict[str, Any]:
    eid = combatant.entity_id
    return {
        "entity_id": eid,
        "name": names.get(eid, combatant.name),
        "initiative": combatant.initiative,
        "hp": live_view.tracked_hp.get(eid, combatant.hp_current),
        "max_hp": combatant.hp_max,
        "dead": eid in live_view.dead_ids,
        "conditions": sorted(live_view.active_conditions.get(eid, set())),
        "zone": live_view.actor_zone.get(eid),
    }


async def _view_route(state: BridgeState, cid: str) -> dict[str, Any]:
    session = _session(state, cid)
    names = session.names
    live_view = get_live(session.handle)
    order = [_order_row(combatant, names, live_view) for combatant in live_view.initiative]

    current_actor = ""
    if 0 <= live_view.current_turn_index < len(live_view.initiative):
        current = live_view.initiative[live_view.current_turn_index]
        current_actor = f"{current.entity_id} ({names.get(current.entity_id, current.name)})"

    return {
        "round_number": live_view.round_number,
        "current_actor": current_actor,
        "order": order,
        "ended": live_view.ended,
        "grid": session.grid.model_dump(),
        "seed": session.seed,
        "turn": dataclasses.asdict(live_view.turn),
        "summons": {k: dataclasses.asdict(v) for k, v in live_view.summons.items()},
        "transformations": {k: dataclasses.asdict(v) for k, v in live_view.transformations.items()},
        "constructs": {k: dataclasses.asdict(v) for k, v in live_view.constructs.items()},
    }


async def _end_route(state: BridgeState, cid: str) -> dict[str, Any]:
    session = _session(state, cid)
    result = await end_combat(session.handle)
    del state.sessions[cid]
    return {
        "outcome": result.outcome.model_dump(),
        "narration": narrate(result.events, session.names),
    }


def build_combat_router(state: BridgeState) -> APIRouter:
    router = APIRouter()

    @router.post("/v1/combat")
    async def start(req: _CombatStartRequest) -> dict[str, Any]:
        return await _start_route(state, req)

    @router.post("/v1/combat/{cid}/intent")
    async def intent(cid: str, req: _IntentRequest) -> dict[str, Any]:
        return await _intent_route(state, cid, req)

    @router.post("/v1/combat/{cid}/advance-monster")
    async def advance_monster(cid: str) -> dict[str, Any]:
        return await _advance_monster_route(state, cid)

    @router.get("/v1/combat/{cid}")
    async def view(cid: str) -> dict[str, Any]:
        return await _view_route(state, cid)

    @router.post("/v1/combat/{cid}/end")
    async def end(cid: str) -> dict[str, Any]:
        return await _end_route(state, cid)

    return router


__all__ = ["build_combat_router"]
