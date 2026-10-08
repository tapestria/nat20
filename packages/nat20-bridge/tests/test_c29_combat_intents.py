"""C29 — bridge parity: every intent field, the view, summons by name.

Transcribed from the local C29 scenario catalog. Every request goes through
the HTTP client. ``POST /v1/combat/{cid}/intent`` takes every
``PlayerIntent`` field and refuses an unknown key or intent type with 422, as
it does an intent the engine can't resolve; ``GET /v1/combat/{cid}`` reports
the turn, the summons, the transformations, the constructs, the seed and each
combatant's Initiative; a summon narrates by its name.

SRD 5.2 Summon Dragon: "it takes its turn immediately after yours ... If you
don't issue any, it takes the Dodge action". Magic Missile: "The spell creates
one more dart for each spell slot level above 1." Wild Shape: "you
shape-shift into a Beast form that you have learned for this feature".
Channel Divinity: "choose which Channel Divinity effect from this class to
create". Cunning Action: "you can take one of the following actions as a
Bonus Action: Dash, Disengage, or Hide." Alert: "When you roll Initiative, you
can add your Proficiency Bonus to the roll."
"""

from __future__ import annotations

import random
from typing import Any

from fastapi.testclient import TestClient

_GOBLIN = "mon:goblin-warrior-1"


def _member(name: str, class_slug: str, level: int, **build: Any) -> dict[str, Any]:
    spells = build.pop("spells_known", None)
    member: dict[str, Any] = {
        "name": name,
        "build": {"species_slug": "human", "class_slug": class_slug, "level": level} | build,
    }
    if spells is not None:
        member["spells_known"] = spells
    return member


def _start(
    client: TestClient, member: dict[str, Any], *, seed: int, monster: str = "goblin-warrior"
) -> str:
    resp = client.post("/v1/combat", json={"party": [member], "monsters": [monster], "seed": seed})
    assert resp.status_code == 200, resp.text
    cid: str = resp.json()["combat_id"]
    return cid


def _view(client: TestClient, cid: str) -> dict[str, Any]:
    resp = client.get(f"/v1/combat/{cid}")
    assert resp.status_code == 200, resp.text
    view: dict[str, Any] = resp.json()
    return view


def _act(client: TestClient, cid: str, actor: str, **intent: Any) -> dict[str, Any]:
    resp = client.post(f"/v1/combat/{cid}/intent", json={"actor_id": actor} | intent)
    assert resp.status_code == 200, resp.text
    body: dict[str, Any] = resp.json()
    return body


def _types(body: dict[str, Any]) -> list[str]:
    return [e["type"] for e in body["events"]]


_VEX = _member(
    "Vex",
    "wizard",
    9,
    ability_scores={"str": 8, "dex": 14, "con": 14, "int": 18, "wis": 12, "cha": 10},
    spells_known=["summon-dragon"],
)


def _summon(client: TestClient) -> tuple[str, str, dict[str, Any]]:
    """Vex (first at seed 42) casts Summon Dragon; the spirit's turn begins."""
    cid = _start(client, _VEX, seed=42)
    cast = _act(client, cid, "char:vex", intent_type="cast_spell", spell_id="summon-dragon")
    [joined] = [e for e in cast["events"] if e["type"] == "combatant_joined"]
    return cid, joined["entity_id"], cast


def test_c29_a_summon_attacks_with_its_stat_block_action(client: TestClient) -> None:
    cid, spirit, _ = _summon(client)
    view = _view(client, cid)
    assert view["summons"][spirit]["owner_id"] == "char:vex"
    assert view["seed"] == 42
    rend = _act(
        client, cid, spirit, intent_type="attack", stat_block_action_id="rend", target_id=_GOBLIN
    )
    assert "attack_failed" not in _types(rend)
    assert [e["attacker_id"] for e in rend["events"] if e["type"] == "attack_rolled"] == [spirit]


def test_c29_a_spell_is_upcast_with_slot_level(client: TestClient) -> None:
    wizard = _member(
        "Elara",
        "wizard",
        5,
        ability_scores={"int": 16, "dex": 14, "con": 14},
        spells_known=["magic-missile"],
    )
    cid = _start(client, wizard, seed=2, monster="ogre")  # seed 2: Elara first
    cast = _act(
        client,
        cid,
        "char:elara",
        intent_type="cast_spell",
        spell_id="magic-missile",
        target_id="mon:ogre-1",
        slot_level=3,
    )
    [spell] = [e for e in cast["events"] if e["type"] == "spell_cast"]
    assert spell["slot_level"] == 3
    assert _types(cast).count("damage_applied") == 5  # three darts and two more


def test_c29_wild_shape_takes_the_named_form(client: TestClient) -> None:
    druid = _member("Bryn", "druid", 2, ability_scores={"wis": 16, "dex": 14, "con": 14})
    cid = _start(client, druid, seed=5)  # seed 5: Bryn first
    _act(
        client, cid, "char:bryn", intent_type="use_feature", feature_id="wild-shape", form_id="wolf"
    )
    assert _view(client, cid)["transformations"]["char:bryn"]["form_slug"] == "wolf"


_CLERIC = _member("Ilse", "cleric", 2, ability_scores={"wis": 16, "dex": 12, "con": 14})


def test_c29_a_feature_activity_is_picked_by_its_id(client: TestClient) -> None:
    cid = _start(client, _CLERIC, seed=5)  # seed 5: Ilse first
    heal = _act(
        client,
        cid,
        "char:ilse",
        intent_type="use_feature",
        feature_id="channel-divinity-cleric",
        activity_id="UdbUwbvrWwgDuNy9",  # Divine Spark: Heal
        target_id="char:ilse",
    )
    assert "healing_applied" in _types(heal)
    # Divine Spark: Save needs a context the engine doesn't supply yet: the
    # bridge answers 422, not 500.
    cid = _start(client, _CLERIC, seed=5)
    resp = client.post(
        f"/v1/combat/{cid}/intent",
        json={
            "actor_id": "char:ilse",
            "intent_type": "use_feature",
            "feature_id": "channel-divinity-cleric",
            "activity_id": "OY9UrTXvlRL0JUoI",
            "target_id": _GOBLIN,
        },
    )
    assert resp.status_code == 422


def test_c29_cunning_action_dashes_as_a_bonus_action(client: TestClient) -> None:
    rogue = _member("Nyx", "rogue", 2, ability_scores={"str": 8, "dex": 16, "con": 14})
    cid = _start(client, rogue, seed=2)  # seed 2: Nyx first
    dash = _act(client, cid, "char:nyx", intent_type="dash", use_bonus_action=True)
    assert [e["budget_consumed"] for e in dash["events"] if e["type"] == "dash_taken"] == [
        "bonus_action"
    ]
    attack = _act(
        client, cid, "char:nyx", intent_type="attack", weapon_id="rapier", target_id=_GOBLIN
    )
    assert "attack_rolled" in _types(attack)


def test_c29_a_bad_intent_type_or_an_unknown_key_is_refused(client: TestClient) -> None:
    cid = _start(client, _VEX, seed=42)  # seed 42: Vex first
    url = f"/v1/combat/{cid}/intent"
    bad_type = client.post(url, json={"actor_id": "char:vex", "intent_type": "fireball"})
    unknown_key = client.post(
        url, json={"actor_id": "char:vex", "intent_type": "pass", "stat_block_action": "rend"}
    )
    assert (bad_type.status_code, unknown_key.status_code) == (422, 422)
    # Nothing reached the engine: it is still Vex's turn.
    assert _view(client, cid)["current_actor"].startswith("char:vex")


def test_c29_a_multiclass_build_starts_a_combat(client: TestClient) -> None:
    kael = {
        "name": "Kael",
        "build": {
            "species_slug": "human",
            "classes": {"fighter": 3, "wizard": 2},
            "ability_scores": {"str": 15, "dex": 14, "con": 14, "int": 14, "wis": 10, "cha": 8},
        },
    }
    cid = _start(client, kael, seed=1)
    [row] = [r for r in _view(client, cid)["order"] if r["entity_id"] == "char:kael"]
    assert row["max_hp"] == 40


def test_c29_the_engine_rolls_initiative_with_the_derived_dexterity_and_alert(
    client: TestClient,
) -> None:
    rogue = _member(
        "Nyx",
        "rogue",
        1,
        ability_scores={"dex": 15},
        background_slug="criminal",
        selected_choices=["background:dex+2,con+1"],
    )
    for seed in (1, 2, 3):
        [row] = [
            r
            for r in _view(client, _start(client, rogue, seed=seed))["order"]
            if r["entity_id"] == "char:nyx"
        ]
        # The party rolls first: d20 + DEX 17's +3 + Alert's Proficiency Bonus +2.
        assert row["initiative"] == random.Random(seed).randint(1, 20) + 3 + 2


def test_c29_a_summon_narrates_by_its_name(client: TestClient) -> None:
    cid, spirit, cast = _summon(client)
    lines = cast["narration"].splitlines()
    assert "Draconic Spirit joins the fight, summoned by Vex." in lines
    assert "Draconic Spirit's turn begins." in lines
    turn = client.post(f"/v1/combat/{cid}/advance-monster", json={}).json()
    assert "Draconic Spirit attempts dodge." in turn["narration"].splitlines()
    assert spirit not in cast["narration"] + turn["narration"]
