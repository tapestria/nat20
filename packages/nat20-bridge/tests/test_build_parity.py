"""``BuildRequest`` carries every ``make_build_spec`` keyword, unchanged."""

from __future__ import annotations

import inspect
from typing import Any

from dnd5e_engine import make_build_spec
from fastapi.testclient import TestClient

from nat20_bridge.models import BuildRequest

# One value per make_build_spec keyword. CharacterBuildSpec checks only the
# class levels' sum, so these need not make a legal character.
_EVERY_KEYWORD: dict[str, Any] = {
    "species_slug": "human",
    "class_slug": "fighter",
    "level": 5,
    "classes": {"fighter": 3, "wizard": 2},
    "subclass_slug": "champion",
    "ability_scores": {"str": 15, "dex": 14, "con": 13, "int": 12, "wis": 10, "cha": 8},
    "equipment": ("longsword", "shield"),
    "selected_choices": ("background:str+2,con+1",),
    "background_slug": "soldier",
    "hp_mode": "rolled",
    "hp_rolls": {"fighter": (6, 3), "wizard": (4, 2)},
    "ac_calc_mode": "default",
    "attuned_items": ("ring-of-protection",),
    "ability_score_method": "standard_array",
}


def test_build_request_has_every_make_build_spec_keyword() -> None:
    assert set(BuildRequest.model_fields) == set(inspect.signature(make_build_spec).parameters)
    assert set(_EVERY_KEYWORD) == set(BuildRequest.model_fields)


def test_every_field_reaches_make_build_spec_unchanged() -> None:
    assert BuildRequest(**_EVERY_KEYWORD).to_build_spec() == make_build_spec(**_EVERY_KEYWORD)


def test_a_saved_character_with_keys_the_bridge_does_not_know_still_validates(
    client: TestClient,
) -> None:
    resp = client.post(
        "/v1/party/validate",
        json={
            "name": "Brom",
            "notes": "met the party at the inn",
            "build": {"species_slug": "human", "class_slug": "fighter", "portrait": "brom.png"},
        },
    )
    assert resp.status_code == 200, resp.text


def test_a_build_the_engine_refuses_is_422(client: TestClient) -> None:
    for build, message in (
        ({"species_slug": "human"}, "needs class_slug or classes"),
        (
            {"species_slug": "human", "classes": {"fighter": 3, "wizard": 2}, "level": 4},
            "does not equal the sum of classes",
        ),
    ):
        resp = client.post("/v1/party/validate", json={"name": "Kael", "build": build})
        assert resp.status_code == 422
        assert message in resp.json()["detail"]


def test_magic_initiate_reaches_the_sheet(client: TestClient) -> None:
    # An Acolyte's Origin feat, with its choices made in a magic-initiate token.
    resp = client.post(
        "/v1/party/validate",
        json={
            "name": "Ilse",
            "build": {
                "species_slug": "dwarf",
                "class_slug": "fighter",
                "background_slug": "acolyte",
                "ability_scores": {"wis": 16},
                "selected_choices": [
                    "magic-initiate:cleric:wis:guidance,sacred-flame:guiding-bolt"
                ],
            },
        },
    )
    assert resp.status_code == 200, resp.text
    member = resp.json()["member"]
    assert member["feats"] == ["magic-initiate"]
    assert member["spell_abilities"] == {
        "guidance": "wis",
        "sacred-flame": "wis",
        "guiding-bolt": "wis",
    }
    assert member["slotless_casts"] == ["guiding-bolt"]
