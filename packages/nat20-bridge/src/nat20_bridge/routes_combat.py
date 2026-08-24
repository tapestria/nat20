"""Combat lifecycle routes: start / intent / advance-monster / view / end.

Event-drain protocol
---------------------

``start_combat`` returns its opening events directly (``StartCombatResult
.events``), but ``submit_player_intent`` / ``advance_monster_turn`` return
``None`` — every event they emit goes exclusively onto the live combat's
internal ``asyncio.Queue``, drainable only through the public
``narration_events(handle)`` async iterator (it terminates only at
``end_combat``, when the engine pushes a ``None`` sentinel).

So each combat gets one persistent background collector task, spawned right
after ``start_combat`` (see ``_start_collector``), that does:

    async for event in narration_events(handle):
        state.events_log[cid].append(event)

and runs for the combat's whole lifetime. Because the collector only wakes
up when the event loop schedules it, a route handler that just awaited an
engine call (which synchronously queued events via ``_emit`` during that
await) must yield control back to the loop before the collector's appended
rows are visible. ``_pump_until_stable`` does exactly that: it awaits
``asyncio.sleep(0)`` in a bounded loop (100 iterations) until
``events_log[cid]``'s length stops growing for two consecutive checks.

Each route captures ``len(events_log[cid])`` before its engine call and
slices the delta after pumping, so a response only reports events produced
by that one request — not the whole combat's history.

This is the "DECISION" path from the design brief; it was verified to work
under ``TestClient`` because httpx's ``TestClient`` runs the whole ASGI app
(including any tasks it spawns) on a single event loop for the lifetime of
the client, so a collector task created during one request is still alive
and pumping during the next.
"""

from __future__ import annotations

import asyncio
import random
import re
from typing import Any

from dnd5e_engine import (
    CombatEvent,
    CombatHandle,
    EncounterMemberSpec,
    GridScene,
    PlayerIntent,
    advance_monster_turn,
    cell_id,
    end_combat,
    get_live,
    make_build_spec,
    narration_events,
    start_combat,
    submit_player_intent,
)
from dnd5e_engine.orchestrator import IntentRejectedError, UnknownHandleError
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from nat20_bridge.models import PartyValidateRequest, resolve_seed, slugify
from nat20_bridge.narrate import narrate
from nat20_bridge.sheet import derive_sheet
from nat20_bridge.state import BridgeState

_PUMP_MAX_ITERATIONS = 100
_PUMP_STABLE_CHECKS = 2

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


def _ability_mod(score: int) -> int:
    return (score - 10) // 2


class _CombatStartRequest(BaseModel):
    party: list[PartyValidateRequest]
    monsters: list[str]
    seed: int | None = None


class _IntentRequest(BaseModel):
    actor_id: str
    intent_type: str
    spell_id: str | None = None
    target_id: str | None = None
    item_id: str | None = None
    weapon_id: str | None = None
    feature_id: str | None = None
    target_zone_id: str | None = None


def _get_handle(state: BridgeState, cid: str) -> CombatHandle:
    handle = state.combats.get(cid)
    if handle is None:
        raise HTTPException(status_code=404, detail=f"unknown combat: {cid!r}")
    return handle


async def _collect_events(handle: CombatHandle, cid: str, state: BridgeState) -> None:
    """Background task: drain ``narration_events`` into ``events_log`` for good."""
    async for event in narration_events(handle):
        state.events_log.setdefault(cid, []).append(event)


async def _pump_until_stable(state: BridgeState, cid: str) -> None:
    """Yield to the loop until the collector task's appends settle.

    The engine's ``_emit`` pushes events onto the live queue synchronously
    during an awaited engine call, but the collector task only sees them
    once the loop schedules it — bounded ``asyncio.sleep(0)`` pump, per the
    module docstring's drain protocol.
    """
    prev_len = -1
    stable = 0
    for _ in range(_PUMP_MAX_ITERATIONS):
        await asyncio.sleep(0)
        cur_len = len(state.events_log.get(cid, []))
        if cur_len == prev_len:
            stable += 1
            if stable >= _PUMP_STABLE_CHECKS:
                return
        else:
            stable = 0
        prev_len = cur_len


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
    state: BridgeState, party: list[PartyValidateRequest], rng: random.Random
) -> tuple[list[Any], dict[str, str]]:
    assert state.loader is not None
    loader = state.loader
    party_specs = []
    names: dict[str, str] = {}
    for i, member_req in enumerate(party):
        entity_id = member_req.entity_id or f"char:{slugify(member_req.name)}"
        try:
            build_spec = make_build_spec(
                species_slug=member_req.build.species_slug,
                class_slug=member_req.build.class_slug,
                level=member_req.build.level,
                subclass_slug=member_req.build.subclass_slug,
                ability_scores=member_req.build.ability_scores.model_dump(by_alias=True),
                equipment=member_req.build.equipment,
            )
            dex_mod = _ability_mod(member_req.build.ability_scores.dex)
            member = derive_sheet(
                build_spec,
                name=_sanitize_name(member_req.name),
                entity_id=entity_id,
                loader=loader,
                hp_current=member_req.hp_current,
                spells_known=member_req.spells_known,
                zone_id=cell_id(0, i),
                initiative=rng.randint(1, 20) + dex_mod,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        party_specs.append(member)
        names[member.entity_id] = member.name
    return party_specs, names


def _build_encounter_specs(
    state: BridgeState, monster_slugs: list[str], rng: random.Random
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
        dex_mod = _ability_mod(monster.ability_scores.dex)
        enc = EncounterMemberSpec(
            entity_id=entity_id,
            entity_type="Monster",
            name=_sanitize_name(f"{monster.name} {n}"),
            initiative=rng.randint(1, 20) + dex_mod,
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


async def _start_route(state: BridgeState, req: _CombatStartRequest) -> dict[str, Any]:
    seed = resolve_seed(req.seed)
    # Legacy dice paths (roll_dice_str et al.) read the stdlib global
    # `random` module rather than an injectable RNG — see app.py's
    # `_do_roll` for the same rationale. Seeding it here (in addition to
    # the engine's own `rng_seed`-threaded RNG) is what makes the
    # same-seed-same-narration test reproducible end to end.
    # KNOWN LIMITATION (accepted, tracked in BACKLOG under Task 15): this
    # mutates process-global state, so two `/v1/combat` requests racing
    # concurrently (different seeds) can have one request's global reseed
    # clobber the other's before its dice resolve — not safe under
    # concurrent load. Fine for the current single-connection ST-bridge
    # usage; a real fix needs the legacy dice paths to accept an injectable
    # RNG instead of reading the global module.
    random.seed(seed)
    rng = random.Random(seed)

    party_specs, party_names = _build_party_specs(state, req.party, rng)
    encounter_specs, monster_names = _build_encounter_specs(state, req.monsters, rng)
    names = {**party_names, **monster_names}

    # Monotonic counter, not `len(state.combats) + 1` — the latter
    # collides once any combat has ended and been popped from `combats`
    # (see BridgeState.next_combat_id's docstring).
    cid = f"c{state.next_combat_id}"
    state.next_combat_id += 1
    result = await start_combat(
        session_id=cid,
        party=party_specs,
        encounter=encounter_specs,
        grid_scene=GridScene(width=12, height=12),
        rng_seed=seed,
    )

    state.combats[cid] = result.handle
    state.events_log[cid] = []
    state.names[cid] = names
    state.seeds[cid] = seed
    state.collectors[cid] = asyncio.create_task(_collect_events(result.handle, cid, state))

    await _pump_until_stable(state, cid)
    events = state.events_log[cid]
    return _envelope(cid, events, names, over=False)


def _player_intent_from_request(req: _IntentRequest) -> PlayerIntent:
    payload = {
        k: v
        for k, v in req.model_dump().items()
        if k not in ("actor_id", "intent_type") and v is not None
    }
    return PlayerIntent(intent_type=req.intent_type, **payload)  # type: ignore[arg-type]


async def _intent_route(state: BridgeState, cid: str, req: _IntentRequest) -> dict[str, Any]:
    handle = _get_handle(state, cid)
    names = state.names.get(cid, {})
    start_idx = len(state.events_log.get(cid, []))
    player_intent = _player_intent_from_request(req)

    try:
        await submit_player_intent(handle, req.actor_id, player_intent)
    except IntentRejectedError as exc:
        raise HTTPException(status_code=409, detail=exc.reason) from exc
    except UnknownHandleError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    await _pump_until_stable(state, cid)
    events = state.events_log.get(cid, [])[start_idx:]
    over = get_live(handle).ended
    return _envelope(cid, events, names, over=over)


async def _advance_monster_route(state: BridgeState, cid: str) -> dict[str, Any]:
    handle = _get_handle(state, cid)
    names = state.names.get(cid, {})
    start_idx = len(state.events_log.get(cid, []))

    try:
        await advance_monster_turn(handle)
    except IntentRejectedError as exc:
        raise HTTPException(status_code=409, detail=exc.reason) from exc
    except UnknownHandleError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    await _pump_until_stable(state, cid)
    events = state.events_log.get(cid, [])[start_idx:]
    over = get_live(handle).ended
    return _envelope(cid, events, names, over=over)


def _order_row(combatant: Any, names: dict[str, str], live_view: Any) -> dict[str, Any]:
    eid = combatant.entity_id
    return {
        "entity_id": eid,
        "name": names.get(eid, combatant.name),
        "hp": live_view.tracked_hp.get(eid, combatant.hp_current),
        "max_hp": combatant.hp_max,
        "dead": eid in live_view.dead_ids,
        "conditions": sorted(live_view.active_conditions.get(eid, set())),
        "zone": live_view.actor_zone.get(eid),
    }


async def _view_route(state: BridgeState, cid: str) -> dict[str, Any]:
    handle = _get_handle(state, cid)
    names = state.names.get(cid, {})
    try:
        live_view = get_live(handle)
    except UnknownHandleError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

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
    }


async def _stop_collector(state: BridgeState, cid: str) -> None:
    task = state.collectors.pop(cid, None)
    if task is None:
        return
    try:
        await asyncio.wait_for(task, timeout=1)
    except (TimeoutError, asyncio.CancelledError):
        task.cancel()


async def _end_route(state: BridgeState, cid: str) -> dict[str, Any]:
    handle = _get_handle(state, cid)
    names = state.names.get(cid, {})
    try:
        result = await end_combat(handle)
    except UnknownHandleError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    await _pump_until_stable(state, cid)
    await _stop_collector(state, cid)
    state.combats.pop(cid, None)

    return {
        "outcome": result.outcome.model_dump(),
        "narration": narrate(result.events, names),
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
