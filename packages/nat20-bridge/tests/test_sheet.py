import pytest
from dnd5e_engine import make_build_spec
from dnd5e_srd_data.loader import BundledAssetLoader
from fastapi.testclient import TestClient

from nat20_bridge.sheet import derive_sheet

LOADER = BundledAssetLoader()


def _wizard(level: int = 3):
    return make_build_spec(
        species_slug="elf-high",
        class_slug="wizard",
        level=level,
        ability_scores={"str": 8, "dex": 14, "con": 13, "int": 15, "wis": 12, "cha": 10},
    )


def test_wizard_hp_ac_slots() -> None:
    m = derive_sheet(
        _wizard(),
        name="Elara",
        entity_id="char:elara",
        loader=LOADER,
        spells_known=["fire-bolt", "magic-missile"],
    )
    # d6 wizard, con 13 (+1): 6+1 + 2*(4+1) = 17
    assert m.hp_max == 17 and m.hp_current == 17
    assert m.ac == 12  # unarmored 10 + dex(+2)
    assert m.spell_slots == {1: 4, 2: 2}  # full caster lvl 3
    assert m.spells_known == ["fire-bolt", "magic-missile"]
    assert m.character_level == 3 and m.class_slug == "wizard"


def test_fighter_armor_and_shield_ac() -> None:
    spec = make_build_spec(
        species_slug="human",
        class_slug="fighter",
        level=1,
        ability_scores={"str": 16, "dex": 14, "con": 14, "int": 10, "wis": 12, "cha": 8},
        equipment=("chain-mail", "shield"),
    )
    m = derive_sheet(spec, name="Brom", entity_id="char:brom", loader=LOADER)
    # chain mail 16 flat (dex cap 0) + shield 2
    assert m.ac == 18
    assert m.spell_slots == {}


def test_unknown_spell_slug_rejected() -> None:
    with pytest.raises(ValueError, match="wizzard-bolt"):
        derive_sheet(
            _wizard(), name="E", entity_id="char:e", loader=LOADER, spells_known=["wizzard-bolt"]
        )


def test_party_validate_route(client: TestClient) -> None:
    resp = client.post(
        "/v1/party/validate",
        json={
            "name": "Elara",
            "build": {
                "species_slug": "elf-high",
                "class_slug": "wizard",
                "level": 3,
                "ability_scores": {"str": 8, "dex": 14, "con": 13, "int": 15, "wis": 12, "cha": 10},
            },
            "spells_known": ["fire-bolt"],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["member"]["hp_max"] == 17
    assert "Elara" in body["summary"]


def test_party_validate_route_bad_class(client: TestClient) -> None:
    resp = client.post(
        "/v1/party/validate",
        json={"name": "X", "build": {"species_slug": "elf-high", "class_slug": "wizzard"}},
    )
    assert resp.status_code == 422
    assert "wizzard" in resp.json()["detail"]
