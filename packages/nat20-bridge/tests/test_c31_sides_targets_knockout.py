"""Allies, a chosen foe target and a knock-out over HTTP.

SRD 5.2 Summon Dragon: "The creature is an ally to you and your allies." A
start body's ``allies`` seats monsters on the party's side.

SRD 5.2 Rules Glossary, Knocking Out a Creature: "When you would reduce a
creature to 0 Hit Points with a melee attack, you can instead reduce the
creature to 1 Hit Point. The creature then has the Unconscious condition and
starts a Short Rest." An intent body's ``knock_out`` makes that choice.

The advance-monster body's ``target_id`` names the creature the acting foe
attacks; the engine refuses a creature the foe could not pick.
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any

from dnd5e_engine import get_live
from dnd5e_engine.testing import rng_factory
from fastapi.testclient import TestClient

from nat20_bridge.app import create_app
from nat20_bridge.state import BridgeState

_BROM = {
    "name": "Brom",
    "build": {
        "species_slug": "human",
        "class_slug": "fighter",
        "level": 3,
        "equipment": ["longsword"],
    },
}
_TESS = {
    "name": "Tess",
    "build": {"species_slug": "human", "class_slug": "fighter", "level": 3},
    "hp_current": 5,
}


class _D20Shows19(random.Random):
    """Every d20 shows 19: every attack hits and none is a natural 20."""

    def randint(self, a: int, b: int) -> int:
        return 19 if (a, b) == (1, 20) else super().randint(a, b)


def _start(client: TestClient, **body: Any) -> dict[str, Any]:
    resp = client.post("/v1/combat", json={"seed": 1} | body)
    assert resp.status_code == 200, resp.text
    start: dict[str, Any] = resp.json()
    return start


def _current(client: TestClient, cid: str) -> str:
    actor: str = client.get(f"/v1/combat/{cid}").json()["current_actor"].split(" ")[0]
    return actor


def _turn_of(client: TestClient, cid: str, actor_id: str) -> None:
    """Pass every character's turn and advance every other creature's until
    ``actor_id`` is up."""
    for _ in range(12):
        actor = _current(client, cid)
        if actor == actor_id:
            return
        if actor.startswith("char:"):
            resp = client.post(
                f"/v1/combat/{cid}/intent", json={"actor_id": actor, "intent_type": "pass"}
            )
        else:
            resp = client.post(f"/v1/combat/{cid}/advance-monster", json={})
        assert resp.status_code == 200, resp.text
    raise AssertionError(f"{actor_id} never came up")


def _view(client: TestClient, cid: str) -> dict[str, Any]:
    view: dict[str, Any] = client.get(f"/v1/combat/{cid}").json()
    return view


# ── Allies ───────────────────────────────────────────────────────────────────


def test_allies_are_seated_on_the_party_side(client: TestClient) -> None:
    start = _start(
        client, party=[_BROM], monsters=["goblin-warrior"], allies=["goblin-warrior", "wolf"]
    )
    cid = start["combat_id"]
    view = _view(client, cid)
    assert view["party_ids"] == ["char:brom", "mon:goblin-warrior-2", "mon:wolf-3"]
    assert view["encounter_ids"] == ["mon:goblin-warrior-1"]
    rows = {row["entity_id"]: row for row in view["order"]}
    assert rows["mon:goblin-warrior-2"]["name"] == "Goblin Warrior 2"
    assert rows["mon:wolf-3"]["name"] == "Wolf 3"
    # Beside the party in column 0, below its last character.
    assert rows["mon:goblin-warrior-2"]["zone"] == "0,1"
    assert rows["mon:wolf-3"]["zone"] == "0,2"


def test_the_engine_seats_allies_with_the_party(tmp_path: Path) -> None:
    state = BridgeState(homebrew_path=tmp_path / "homebrew.json")
    client = TestClient(create_app(state))
    cid = _start(client, party=[_BROM], monsters=["goblin-warrior"], allies=["wolf"])["combat_id"]
    live = get_live(state.sessions[cid].handle)
    assert live.party_ids == {"char:brom", "mon:wolf-2"}
    assert live.encounter_ids == {"mon:goblin-warrior-1"}


def test_an_ally_turn_attacks_a_foe(client: TestClient) -> None:
    cid = _start(client, party=[_BROM], monsters=["goblin-warrior"], allies=["wolf"])["combat_id"]
    _turn_of(client, cid, "mon:wolf-2")
    turn = client.post(f"/v1/combat/{cid}/advance-monster", json={}).json()
    targets = [e["target_id"] for e in turn["events"] if e["type"] == "attack_rolled"]
    assert targets
    assert set(targets) == {"mon:goblin-warrior-1"}


def test_allies_alone_are_no_fight(client: TestClient) -> None:
    resp = client.post(
        "/v1/combat", json={"party": [_BROM], "monsters": [], "allies": ["wolf"], "seed": 1}
    )
    assert resp.status_code == 422
    assert "encounter" in resp.json()["detail"]


def test_an_unknown_ally_is_404(client: TestClient) -> None:
    resp = client.post(
        "/v1/combat",
        json={"party": [_BROM], "monsters": ["goblin-warrior"], "allies": ["nope"], "seed": 1},
    )
    assert resp.status_code == 404


# ── A chosen foe target ──────────────────────────────────────────────────────


def test_a_chosen_target_reaches_the_engine(client: TestClient) -> None:
    # Tess at 5 HP is the goblin's own pick; the body sends it at Brom.
    cid = _start(client, party=[_BROM, _TESS], monsters=["goblin-warrior"])["combat_id"]
    _turn_of(client, cid, "mon:goblin-warrior-1")
    resp = client.post(f"/v1/combat/{cid}/advance-monster", json={"target_id": "char:brom"})
    assert resp.status_code == 200, resp.text
    events = resp.json()["events"]
    [submitted] = [e for e in events if e["type"] == "intent_submitted"]
    assert submitted["target_id"] == "char:brom"
    assert {e["target_id"] for e in events if e["type"] == "attack_rolled"} == {"char:brom"}


def test_an_illegal_target_is_409_and_leaves_nothing(client: TestClient) -> None:
    cid = _start(client, party=[_BROM], monsters=["goblin-warrior"])["combat_id"]
    _turn_of(client, cid, "mon:goblin-warrior-1")
    for target_id in ("mon:goblin-warrior-1", "char:nobody"):
        refused = client.post(f"/v1/combat/{cid}/advance-monster", json={"target_id": target_id})
        assert (refused.status_code, refused.json()["detail"]) == (409, "target_invalid")
    assert _current(client, cid) == "mon:goblin-warrior-1"
    turn = client.post(f"/v1/combat/{cid}/advance-monster", json={}).json()
    submitted = [e["actor_id"] for e in turn["events"] if e["type"] == "intent_submitted"]
    assert submitted == ["mon:goblin-warrior-1"]


def test_advance_takes_no_body_or_an_empty_one(client: TestClient) -> None:
    # Seed 1 puts the goblin first.
    bodies: list[dict[str, Any] | None] = [{}, None]
    for body in bodies:
        cid = _start(client, party=[_BROM], monsters=["goblin-warrior"])["combat_id"]
        assert _current(client, cid) == "mon:goblin-warrior-1"
        resp = client.post(f"/v1/combat/{cid}/advance-monster", json=body)
        assert resp.status_code == 200, resp.text
        submitted = [
            e["actor_id"] for e in resp.json()["events"] if e["type"] == "intent_submitted"
        ]
        assert submitted == ["mon:goblin-warrior-1"]


def test_an_unknown_advance_key_is_422(client: TestClient) -> None:
    cid = _start(client, party=[_BROM], monsters=["goblin-warrior"])["combat_id"]
    resp = client.post(f"/v1/combat/{cid}/advance-monster", json={"target": "char:brom"})
    assert resp.status_code == 422
    assert _current(client, cid) == "mon:goblin-warrior-1"


# ── Knocking out ─────────────────────────────────────────────────────────────


def _frail_goblin(client: TestClient) -> str:
    """A homebrew Goblin Warrior with 1 Hit Point (of 1, so it never flees)."""
    raw = client.get("/v1/srd/monsters/goblin-warrior").json()
    raw["slug"] = "hb-frail-goblin"
    raw["name"] = "Frail Goblin"
    raw["hp"] = 1
    resp = client.post("/v1/homebrew/monsters", json=raw)
    assert resp.status_code == 200, resp.text
    slug: str = resp.json()["slug"]
    return slug


def test_a_pulled_blow_knocks_the_foe_out(client: TestClient) -> None:
    slug = _frail_goblin(client)
    with rng_factory(_D20Shows19):
        cid = _start(client, party=[_BROM], monsters=[slug])["combat_id"]
    _turn_of(client, cid, "char:brom")
    resp = client.post(
        f"/v1/combat/{cid}/intent",
        json={
            "actor_id": "char:brom",
            "intent_type": "attack",
            "weapon_id": "longsword",
            "target_id": f"mon:{slug}-1",
            "knock_out": True,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert {"type": "knocked_out", "target_id": f"mon:{slug}-1", "attacker_id": "char:brom"} in (
        body["events"]
    )
    assert "Brom knocks Frail Goblin 1 out." in body["narration"].splitlines()

    view = _view(client, cid)
    assert view["knocked_out_ids"] == [f"mon:{slug}-1"]
    assert view["deaths"] == []
    [row] = [r for r in view["order"] if r["entity_id"] == f"mon:{slug}-1"]
    assert (row["hp"], row["dead"]) == (1, False)
    assert "unconscious" in row["conditions"]

    outcome = client.post(f"/v1/combat/{cid}/end").json()["outcome"]
    assert outcome["ended_reason"] == "victory"
    assert outcome["deaths"] == []
    assert outcome["knock_outs"] == [
        {"target_id": f"mon:{slug}-1", "target_kind": "monster", "attacker_id": "char:brom"}
    ]


def test_a_kill_shows_in_the_views_deaths(client: TestClient) -> None:
    slug = _frail_goblin(client)
    with rng_factory(_D20Shows19):
        cid = _start(client, party=[_BROM], monsters=[slug, slug])["combat_id"]
    _turn_of(client, cid, "char:brom")
    resp = client.post(
        f"/v1/combat/{cid}/intent",
        json={
            "actor_id": "char:brom",
            "intent_type": "attack",
            "weapon_id": "longsword",
            "target_id": f"mon:{slug}-1",
        },
    )
    assert resp.status_code == 200, resp.text
    view = _view(client, cid)
    [death] = view["deaths"]
    assert (death["target_id"], death["target_kind"], death["reason"], death["killer_id"]) == (
        f"mon:{slug}-1",
        "monster",
        "damage",
        "char:brom",
    )
    assert view["knocked_out_ids"] == []


def test_a_pulled_blow_that_is_not_melee_is_409(client: TestClient) -> None:
    archer = {
        "name": "Brom",
        "build": {
            "species_slug": "human",
            "class_slug": "fighter",
            "level": 3,
            "equipment": ["shortbow"],
        },
    }
    cid = _start(client, party=[archer], monsters=["goblin-warrior"])["combat_id"]
    _turn_of(client, cid, "char:brom")
    refused = client.post(
        f"/v1/combat/{cid}/intent",
        json={
            "actor_id": "char:brom",
            "intent_type": "attack",
            "weapon_id": "shortbow",
            "target_id": "mon:goblin-warrior-1",
            "knock_out": True,
        },
    )
    assert (refused.status_code, refused.json()["detail"]) == (409, "knock_out_not_melee")
    turn = client.post(
        f"/v1/combat/{cid}/intent", json={"actor_id": "char:brom", "intent_type": "pass"}
    ).json()
    assert [e["type"] for e in turn["events"]].count("intent_submitted") == 1
