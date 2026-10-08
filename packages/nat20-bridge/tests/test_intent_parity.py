"""Every ``PlayerIntent`` field reaches the engine; a refused intent leaves
nothing behind; the view's turn and constructs."""

from __future__ import annotations

from typing import Any

import pytest
from dnd5e_engine import PlayerIntent
from fastapi.testclient import TestClient

from nat20_bridge import routes_combat

# One value per PlayerIntent field, each valid for its field (these need not
# make an intent the engine could resolve: the engine is stubbed below).
_EVERY_FIELD: dict[str, Any] = {
    "intent_type": "attack",
    "spell_id": "fire-bolt",
    "target_id": "mon:goblin-warrior-1",
    "target_ids": ["mon:goblin-warrior-1", "mon:goblin-warrior-1"],
    "item_id": "potion-of-healing",
    "weapon_id": "longsword",
    "feature_id": "second-wind",
    "activity_id": "UdbUwbvrWwgDuNy9",
    "slot_level": 3,
    "charges_to_spend": 2,
    "pool_points": 5,
    "redeem_granted_die": "feature_grant:bardic-inspiration",
    "reaction_trigger": "hit_by_attack",
    "target_zone_id": "3,4",
    "direction": [1, -1],
    "excluded_target_ids": ["char:brom"],
    "use_bonus_action": True,
    "shove_push": True,
    "two_handed": True,
    "as_ritual": True,
    "form_id": "wolf",
    "stat_block_action_id": "rend",
}

_BROM = {"name": "Brom", "build": {"species_slug": "human", "class_slug": "fighter", "level": 3}}


def _start(client: TestClient, member: dict[str, Any], *, seed: int) -> str:
    resp = client.post(
        "/v1/combat", json={"party": [member], "monsters": ["goblin-warrior"], "seed": seed}
    )
    assert resp.status_code == 200, resp.text
    cid: str = resp.json()["combat_id"]
    return cid


def test_every_intent_field_reaches_the_engine_unchanged(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert set(_EVERY_FIELD) == set(PlayerIntent.model_fields)
    received: list[tuple[str, PlayerIntent]] = []

    async def _receive(handle: object, actor_id: str, intent: PlayerIntent) -> None:
        received.append((actor_id, intent))

    monkeypatch.setattr(routes_combat, "submit_player_intent", _receive)
    cid = _start(client, _BROM, seed=1)
    resp = client.post(f"/v1/combat/{cid}/intent", json={"actor_id": "char:brom"} | _EVERY_FIELD)
    assert resp.status_code == 200, resp.text
    assert received == [("char:brom", PlayerIntent(**_EVERY_FIELD))]


def test_a_zero_direction_is_422(client: TestClient) -> None:
    cid = _start(client, _BROM, seed=1)
    resp = client.post(
        f"/v1/combat/{cid}/intent",
        json={"actor_id": "char:brom", "intent_type": "move", "direction": [0, 0]},
    )
    assert resp.status_code == 422
    assert "nonzero" in str(resp.json()["detail"])


_CLERIC = {
    "name": "Ilse",
    "build": {
        "species_slug": "human",
        "class_slug": "cleric",
        "level": 3,
        "ability_scores": {"wis": 16, "dex": 12, "con": 14},
    },
    "spells_known": ["spiritual-weapon"],
}


def test_a_refused_intent_leaves_nothing_for_the_next_response(client: TestClient) -> None:
    cid = _start(client, _CLERIC, seed=5)  # seed 5: Ilse first
    url = f"/v1/combat/{cid}/intent"
    # Divine Spark: Save queues its intent_submitted, then the engine raises.
    save = client.post(
        url,
        json={
            "actor_id": "char:ilse",
            "intent_type": "use_feature",
            "feature_id": "channel-divinity-cleric",
            "activity_id": "OY9UrTXvlRL0JUoI",
            "target_id": "mon:goblin-warrior-1",
        },
    )
    assert save.status_code == 422
    passed = client.post(url, json={"actor_id": "char:ilse", "intent_type": "pass"})
    submitted = [e for e in passed.json()["events"] if e["type"] == "intent_submitted"]
    assert [(e["actor_id"], e["intent_type"]) for e in submitted] == [("char:ilse", "pass")]


def test_the_view_reports_a_spiritual_weapon_and_the_turn(client: TestClient) -> None:
    cid = _start(client, _CLERIC, seed=5)  # seed 5: Ilse first
    cast = client.post(
        f"/v1/combat/{cid}/intent",
        json={
            "actor_id": "char:ilse",
            "intent_type": "cast_spell",
            "spell_id": "spiritual-weapon",
            "target_zone_id": "2,0",
            "target_id": "mon:goblin-warrior-1",
        },
    )
    assert cast.status_code == 200, cast.text
    view = client.get(f"/v1/combat/{cid}").json()
    [force] = view["constructs"].values()
    assert (force["owner_id"], force["spell_id"], force["zone_id"]) == (
        "char:ilse",
        "spiritual-weapon",
        "2,0",
    )
    # A Bonus Action spell: Ilse's Action, and its one attack, are still hers.
    assert view["current_actor"].startswith("char:ilse")
    assert view["turn"] == {"attacks_remaining": 1, "extra_actions_remaining": 0}


_VEX = {
    "name": "Vex",
    "build": {
        "species_slug": "human",
        "class_slug": "wizard",
        "level": 9,
        "ability_scores": {"int": 18, "dex": 14, "con": 14},
    },
    "spells_known": ["summon-dragon"],
}


def test_a_refused_call_still_names_a_creature_that_joined(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The engine raises after the spirit joined: what the call queued is
    # dropped, but the spirit narrates by its name from then on.
    real = routes_combat.submit_player_intent

    async def _summon_then_raise(handle: object, actor_id: str, intent: PlayerIntent) -> None:
        await real(handle, actor_id, intent)
        raise ValueError("a part of the spell the engine can't resolve")

    cid = _start(client, _VEX, seed=42)  # seed 42: Vex first
    monkeypatch.setattr(routes_combat, "submit_player_intent", _summon_then_raise)
    cast = client.post(
        f"/v1/combat/{cid}/intent",
        json={"actor_id": "char:vex", "intent_type": "cast_spell", "spell_id": "summon-dragon"},
    )
    assert cast.status_code == 422
    turn = client.post(f"/v1/combat/{cid}/advance-monster", json={})
    assert "Draconic Spirit attempts dodge." in turn.json()["narration"].splitlines()
