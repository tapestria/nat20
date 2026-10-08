"""C29 — bridge parity: character builds, roll and check.

Transcribed from the local C29 scenario catalog. Every request goes through
the HTTP client. ``/v1/party/validate`` and ``/v1/combat`` take every
``make_build_spec`` keyword; ``/v1/roll`` and ``/v1/check`` roll on a
generator seeded from the request, never on the process-global ``random``.

SRD 5.2 Multiclassing: "You gain the Hit Points from your new class as
described for levels after 1"; Spell Slots — "All your levels in the Bard,
Cleric, Druid, Sorcerer, and Wizard classes". Hit Points: "Each time you gain
a level ... Roll that die, add your Constitution modifier to the roll ...
Instead of rolling, you can use the fixed value". Attack Roll Abilities:
"Dexterity — Ranged attack with a weapon"; "the Finesse property ... lets you
use Strength or Dexterity with a weapon that has that property."
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from nat20_bridge.app import create_app
from nat20_bridge.state import BridgeState


def _validate(client: TestClient, build: dict[str, Any]) -> dict[str, Any]:
    resp = client.post("/v1/party/validate", json={"name": "Kael", "build": build})
    assert resp.status_code == 200, resp.text
    member: dict[str, Any] = resp.json()["member"]
    return member


def test_c29_a_multiclass_build_validates_without_a_level(client: TestClient) -> None:
    member = _validate(
        client,
        {
            "species_slug": "human",
            "classes": {"fighter": 3, "wizard": 2},
            "ability_scores": {"str": 15, "dex": 14, "con": 14, "int": 14, "wis": 10, "cha": 8},
        },
    )
    assert (member["character_level"], member["classes"]) == (5, {"fighter": 3, "wizard": 2})
    # Wizard 2 alone sets the slots; Fighter d10s then Wizard d6s, CON +2 each level.
    assert member["spell_slots"] == {"1": 3}
    assert member["hp_max"] == 40


def test_c29_rolled_hit_points_reach_the_sheet(client: TestClient) -> None:
    fighter: dict[str, Any] = {
        "species_slug": "human",
        "class_slug": "fighter",
        "level": 3,
        "ability_scores": {"con": 14},
    }
    rolled = _validate(client, fighter | {"hp_mode": "rolled", "hp_rolls": {"fighter": [6, 3]}})
    assert rolled["hp_max"] == 12 + (6 + 2) + (3 + 2)
    assert _validate(client, fighter)["hp_max"] == 12 + 8 + 8  # fixed: 6 + 2 per level
    resp = client.post(
        "/v1/party/validate", json={"name": "Kael", "build": fighter | {"hp_mode": "average"}}
    )
    assert resp.status_code == 422


def test_c29_a_background_raises_the_derived_dexterity(client: TestClient) -> None:
    member = _validate(
        client,
        {
            "species_slug": "human",
            "class_slug": "rogue",
            "ability_scores": {"dex": 15},
            "background_slug": "criminal",
            "selected_choices": ["background:dex+2,con+1"],
        },
    )
    assert member["dexterity"] == 17
    assert member["feats"] == ["alert"]  # the Criminal's Origin feat


_ROLL = {"dice": "2d6+3", "seed": 42}
_CHECK = {
    "kind": "skill",
    "ability": "dex",
    "skill": "stealth",
    "dc": 10,
    "ability_scores": {"str": 10, "dex": 16, "con": 10, "int": 10, "wis": 10, "cha": 10},
    "proficient_skills": ["stealth"],
    "proficiency_bonus": 2,
    "seed": 7,
}


def _forbid_global_random(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refuse(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("the process-global random module was used")

    for name in ("seed", "random", "randint", "randrange", "choice", "getrandbits", "uniform"):
        monkeypatch.setattr(random, name, _refuse)


def test_c29_roll_and_check_never_touch_the_global_random(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _forbid_global_random(monkeypatch)
    roll = client.post("/v1/roll", json=_ROLL)
    check = client.post("/v1/check", json=_CHECK)
    assert (roll.status_code, check.status_code) == (200, 200)
    # The same dice 0.6.0 rolled for these seeds.
    assert roll.json()["total"] == 10
    assert (check.json()["natural_roll"], check.json()["roll_total"]) == (11, 16)


_ROGUE = {
    "name": "Nyx",
    "build": {
        "species_slug": "human",
        "class_slug": "rogue",
        "ability_scores": {"str": 8, "dex": 16},
    },
}


def _first_attack(client: TestClient, weapon: str) -> dict[str, Any]:
    # Seed 2: the rogue acts first.
    start = client.post(
        "/v1/combat", json={"party": [_ROGUE], "monsters": ["goblin-warrior"], "seed": 2}
    )
    cid = start.json()["combat_id"]
    resp = client.post(
        f"/v1/combat/{cid}/intent",
        json={
            "actor_id": "char:nyx",
            "intent_type": "attack",
            "weapon_id": weapon,
            "target_id": "mon:goblin-warrior-1",
        },
    )
    assert resp.status_code == 200, resp.text
    return next(e for e in resp.json()["events"] if e["type"] == "attack_rolled")


def test_c29_to_hit_is_per_weapon_not_a_flat_attack_bonus(
    client: TestClient, tmp_path: Path
) -> None:
    assert "attack_bonus" not in _validate(client, _ROGUE["build"])
    # A Rogue 1 with DEX 16: Proficiency Bonus +2 and Dexterity +3, through
    # the rapier's Finesse and with the shortbow alike. The fight runs on one
    # event loop, as under a real server.
    state = BridgeState(homebrew_path=tmp_path / "homebrew.json")
    with TestClient(create_app(state)) as fight:
        assert _first_attack(fight, "rapier")["modifier"] == 5
        assert _first_attack(fight, "shortbow")["modifier"] == 5
