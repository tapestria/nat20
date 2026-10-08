"""Combat sessions: the start route's refusals, eviction, and what each response reports."""

from __future__ import annotations

from pathlib import Path

import pytest
from dnd5e_engine import get_live
from fastapi.testclient import TestClient

from nat20_bridge import routes_combat
from nat20_bridge.app import create_app
from nat20_bridge.state import BridgeState

_BROM = {"name": "Brom", "build": {"species_slug": "human", "class_slug": "fighter", "level": 3}}


def test_a_side_the_grid_cannot_seat_is_422_not_500(client: TestClient) -> None:
    # The bridge seats each side in one 12-cell column of its 12x12 grid.
    for party, monsters in (
        ([_BROM], []),
        ([], ["goblin-warrior"]),
        ([_BROM], ["goblin-warrior"] * 13),
    ):
        resp = client.post("/v1/combat", json={"party": party, "monsters": monsters, "seed": 1})
        assert resp.status_code == 422, (len(party), len(monsters), resp.text)


def test_an_evicted_combat_is_ended_in_the_engine(tmp_path: Path) -> None:
    state = BridgeState(homebrew_path=tmp_path / "homebrew.json", max_combats=1)
    client = TestClient(create_app(state))
    first = client.post(
        "/v1/combat", json={"party": [_BROM], "monsters": ["goblin-warrior"], "seed": 1}
    ).json()["combat_id"]
    handle = state.sessions[first].handle
    second = client.post(
        "/v1/combat", json={"party": [_BROM], "monsters": ["goblin-warrior"], "seed": 2}
    ).json()["combat_id"]
    assert list(state.sessions) == [second]
    assert get_live(handle).ended  # ended, so the engine itself can release it


def test_each_response_reports_its_own_requests_events(client: TestClient) -> None:
    # Any client, one event loop or not: the route drains what its own engine
    # call queued.
    start = client.post(
        "/v1/combat", json={"party": [_BROM], "monsters": ["goblin-warrior"], "seed": 1}
    ).json()
    cid = start["combat_id"]
    assert [e["type"] for e in start["events"]][:2] == ["round_started", "turn_phase"]
    actor = client.get(f"/v1/combat/{cid}").json()["current_actor"].split(" ")[0]
    if actor.startswith("char:"):
        turn = client.post(
            f"/v1/combat/{cid}/intent", json={"actor_id": actor, "intent_type": "pass"}
        ).json()
    else:
        turn = client.post(f"/v1/combat/{cid}/advance-monster", json={}).json()
    submitted = [e for e in turn["events"] if e["type"] == "intent_submitted"]
    assert [e["actor_id"] for e in submitted] == [actor]


def test_a_monster_turn_the_engine_cannot_resolve_leaves_nothing_behind(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Seed 1 puts the goblin first. A turn that queues its events and then
    # raises stays a server error, and the next response holds only its own.
    real = routes_combat.advance_monster_turn

    async def _resolve_then_raise(handle: object) -> None:
        await real(handle)
        raise ValueError("a stat block the engine can't resolve")

    cid = client.post(
        "/v1/combat", json={"party": [_BROM], "monsters": ["goblin-warrior"], "seed": 1}
    ).json()["combat_id"]
    monkeypatch.setattr(routes_combat, "advance_monster_turn", _resolve_then_raise)
    with pytest.raises(ValueError, match="can't resolve"):
        client.post(f"/v1/combat/{cid}/advance-monster", json={})
    turn = client.post(
        f"/v1/combat/{cid}/intent", json={"actor_id": "char:brom", "intent_type": "pass"}
    ).json()
    submitted = [e["actor_id"] for e in turn["events"] if e["type"] == "intent_submitted"]
    assert submitted == ["char:brom"]


def test_an_engine_fault_on_an_intent_leaves_nothing_behind(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Seed 1 puts the goblin first, then Brom. An engine fault of any type
    # stays a server error, and the next response holds only its own events.
    real = routes_combat.submit_player_intent

    async def _resolve_then_fail(handle: object, actor_id: str, intent: object) -> None:
        await real(handle, actor_id, intent)
        raise KeyError("an engine fault")

    cid = client.post(
        "/v1/combat", json={"party": [_BROM], "monsters": ["goblin-warrior"], "seed": 1}
    ).json()["combat_id"]
    assert client.post(f"/v1/combat/{cid}/advance-monster", json={}).status_code == 200
    monkeypatch.setattr(routes_combat, "submit_player_intent", _resolve_then_fail)
    with pytest.raises(KeyError, match="an engine fault"):
        client.post(
            f"/v1/combat/{cid}/intent", json={"actor_id": "char:brom", "intent_type": "pass"}
        )
    turn = client.post(f"/v1/combat/{cid}/advance-monster", json={}).json()
    submitted = [e["actor_id"] for e in turn["events"] if e["type"] == "intent_submitted"]
    assert submitted == ["mon:goblin-warrior-1"]
