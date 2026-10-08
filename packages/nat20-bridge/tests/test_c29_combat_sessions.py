"""C29 — bridge parity: combat sessions, their dice and their retention.

Transcribed from the local C29 scenario catalog. Every request goes through
the HTTP client. The engine rolls each combatant's Initiative from the
combat's own seeded generator, so a seeded combat never reads the
process-global ``random`` and its first attack no longer replays an
Initiative roll; at most ``max_combats`` combats stay live, the least
recently used ending first.

SRD 5.2 Initiative: "every participant rolls Initiative; they make a
Dexterity check".
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from nat20_bridge.app import create_app
from nat20_bridge.state import BridgeState

_BROM = {
    "name": "Brom",
    "build": {
        "species_slug": "human",
        "class_slug": "fighter",
        "level": 3,
        "ability_scores": {"str": 16, "dex": 14, "con": 14, "int": 10, "wis": 12, "cha": 8},
        "equipment": ["chain-mail", "shield"],
    },
}
_GOBLIN = "mon:goblin-warrior-1"


def _start(client: TestClient, seed: int) -> str:
    resp = client.post(
        "/v1/combat", json={"party": [_BROM], "monsters": ["goblin-warrior"], "seed": seed}
    )
    assert resp.status_code == 200, resp.text
    cid: str = resp.json()["combat_id"]
    return cid


def _brom_first(client: TestClient, cid: str) -> bool:
    current: str = client.get(f"/v1/combat/{cid}").json()["current_actor"]
    return current.startswith("char:brom")


def _first_attack(client: TestClient, cid: str) -> dict[str, Any]:
    """The first round's first attack roll: Brom's longsword, or the goblin's."""
    if _brom_first(client, cid):
        resp = client.post(
            f"/v1/combat/{cid}/intent",
            json={
                "actor_id": "char:brom",
                "intent_type": "attack",
                "weapon_id": "longsword",
                "target_id": _GOBLIN,
            },
        )
    else:
        resp = client.post(f"/v1/combat/{cid}/advance-monster", json={})
    assert resp.status_code == 200, resp.text
    return next(e for e in resp.json()["events"] if e["type"] == "attack_rolled")


def test_c29_a_seeded_combat_never_touches_the_global_random(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _refuse(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("the process-global random module was used")

    for name in ("seed", "random", "randint", "randrange", "choice", "getrandbits", "uniform"):
        monkeypatch.setattr(random, name, _refuse)
    cid = _start(client, seed=7)
    _first_attack(client, cid)
    assert client.get(f"/v1/combat/{cid}").status_code == 200
    assert client.post(f"/v1/combat/{cid}/end", json={}).status_code == 200


def test_c29_the_first_attack_no_longer_replays_the_initiative_roll(client: TestClient) -> None:
    brom_first = replays = 0
    for seed in range(1000, 1400):
        cid = _start(client, seed)
        brom_first += _brom_first(client, cid)
        # Brom rolls Initiative first, so his d20 is the seed's first draw.
        initiative_d20 = random.Random(seed).randint(1, 20)
        replays += _first_attack(client, cid)["natural"] == initiative_d20
        client.post(f"/v1/combat/{cid}/end", json={})
    # The same Initiative as 0.6.0, so the same turn order...
    assert brom_first == 187
    # ...but the first attack's d20 no longer repeats Brom's Initiative d20
    # (0.6.0: 400 of 400); by chance about 1 in 20 does.
    assert replays <= 30


def _app(tmp_path: Path, max_combats: int) -> TestClient:
    state = BridgeState(homebrew_path=tmp_path / "homebrew.json", max_combats=max_combats)
    return TestClient(create_app(state))


def _alive(client: TestClient, cid: str) -> bool:
    resp = client.get(f"/v1/combat/{cid}")
    assert resp.status_code in (200, 404), resp.text
    if resp.status_code == 404:
        assert "expired" in resp.json()["detail"]
    return resp.status_code == 200


def test_c29_the_least_recently_used_combat_ends_past_the_cap(tmp_path: Path) -> None:
    client = _app(tmp_path, max_combats=2)
    c1, c2, c3 = _start(client, 1), _start(client, 2), _start(client, 3)
    assert [_alive(client, cid) for cid in (c1, c2, c3)] == [False, True, True]

    client = _app(tmp_path, max_combats=2)
    c1, c2 = _start(client, 1), _start(client, 2)
    assert _alive(client, c1)  # c1 is now the most recently used
    c3 = _start(client, 3)
    assert [_alive(client, cid) for cid in (c1, c2, c3)] == [True, False, True]


def test_c29_ending_a_combat_releases_its_session(tmp_path: Path) -> None:
    state = BridgeState(homebrew_path=tmp_path / "homebrew.json")
    client = TestClient(create_app(state))
    cid = _start(client, 1)
    assert client.post(f"/v1/combat/{cid}/end", json={}).status_code == 200
    assert state.sessions == {}
    assert client.post(f"/v1/combat/{cid}/end", json={}).status_code == 404
