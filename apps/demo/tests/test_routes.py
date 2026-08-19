"""Route tests — the app shell's GET surface, hit through a real ASGI client.

Every test drives ``create_app()`` end-to-end (real scenario replays, real
Jinja templates); nothing here mocks the engine or the renderers.
"""

from __future__ import annotations

import pytest
from dnd5e_engine import PlayerIntent, cell_id

from nat20_demo.replay import FightLog, IntentCommand, encode_log
from nat20_demo.scenarios import all_scenarios, get_scenario


@pytest.fixture
def client():
    from httpx import ASGITransport, AsyncClient

    from nat20_demo.app import create_app

    return AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://demo")


async def test_catalog_lists_all_scenarios(client) -> None:
    resp = await client.get("/")
    assert resp.status_code == 200
    body = resp.text
    for scenario in all_scenarios():
        assert scenario.title in body
        assert scenario.proves in body


async def test_play_empty_log_renders_board(client) -> None:
    resp = await client.get("/play/goblin-ambush")
    assert resp.status_code == 200
    body = resp.text
    # Grid cells rendered.
    assert 'class="grid"' in body
    assert "cell" in body
    # Initiative rail present.
    assert "Brynn" in body
    assert "Sera" in body
    # Action buttons for Brynn present (she goes first on an empty log).
    assert "Attack — Longsword" in body


async def test_play_with_log_param_renders_replayed_state(client) -> None:
    scenario = get_scenario("goblin-ambush")
    move_steps = [(2, 4), (3, 4), (4, 4), (5, 4), (6, 4), (7, 3)]
    log = FightLog(
        scenario_id=scenario.id,
        seed=scenario.default_seed,
        commands=[
            *[
                IntentCommand(
                    actor="char:brynn",
                    intent=PlayerIntent(intent_type="move", target_zone_id=cell_id(c, r)),
                )
                for c, r in move_steps
            ],
            IntentCommand(
                actor="char:brynn",
                intent=PlayerIntent(
                    intent_type="attack", weapon_id="longsword", target_id="mon:gob1"
                ),
            ),
        ],
    )
    encoded = encode_log(log)
    resp = await client.get(f"/play/goblin-ambush?log={encoded}")
    assert resp.status_code == 200
    body = resp.text
    assert "Brynn attacks Goblin 1" in body


async def test_play_unknown_scenario_404(client) -> None:
    resp = await client.get("/play/not-a-real-scenario")
    assert resp.status_code == 404
    body = resp.text
    assert 'href="/"' in body


async def test_play_malformed_log_400(client) -> None:
    resp = await client.get("/play/goblin-ambush?log=!!!")
    assert resp.status_code == 400


async def test_about_has_attribution(client) -> None:
    resp = await client.get("/about")
    assert resp.status_code == 200
    assert "not affiliated with or endorsed by Wizards of the Coast" in resp.text
