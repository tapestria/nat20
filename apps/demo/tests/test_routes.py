"""Route tests — the app shell's GET surface, hit through a real ASGI client.

Every test drives ``create_app()`` end-to-end (real scenario replays, real
Jinja templates); nothing here mocks the engine or the renderers.
"""

from __future__ import annotations

import base64

import pytest
from dnd5e_engine import PlayerIntent, cell_id

from nat20_demo.replay import MAX_ENCODED_LOG_BYTES, FightLog, IntentCommand, encode_log
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
    assert "Malformed fight log" in resp.text


# A payload that would prove reflected XSS if the GET /play malformed-log
# branch ever forwarded the raw pydantic ``ValidationError`` text (which can
# echo the attacker-controlled decoded payload verbatim) instead of the
# fixed, safe message.
_XSS_PAYLOAD = "<img src=x onerror=alert(1)>"


async def test_play_malformed_log_400_no_xss_reflection(client) -> None:
    poisoned_log = base64.urlsafe_b64encode(_XSS_PAYLOAD.encode()).decode()
    resp = await client.get("/play/goblin-ambush", params={"log": poisoned_log})
    assert resp.status_code == 400
    body = resp.text
    assert "Malformed fight log" in body
    assert _XSS_PAYLOAD not in body
    assert "<img" not in body
    assert "onerror=" not in body


async def test_play_oversized_log_400() -> None:
    # An oversized ``log`` value can't be driven through httpx's
    # ``AsyncClient`` (its own client-side URL-length guard --
    # ``httpx._urlparse.MAX_URL_LENGTH`` -- is 65536 bytes, effectively
    # the same order of magnitude as our ``MAX_ENCODED_LOG_BYTES`` cap, so
    # any query string that trips our 400 also trips httpx's own
    # ``InvalidURL`` before the request is ever sent -- a real-world proxy
    # for the browser URL-length limits that already bound this in
    # practice). Drive the ASGI app directly with a raw scope instead, to
    # prove the guard fires through the real GET /play handler.
    from nat20_demo.app import create_app

    app = create_app()
    huge = "A" * (MAX_ENCODED_LOG_BYTES + 1)
    query_string = ("log=" + huge).encode()
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/play/goblin-ambush",
        "raw_path": b"/play/goblin-ambush",
        "query_string": query_string,
        "headers": [],
        "server": ("demo", 80),
        "client": ("test", 0),
    }
    status_holder: dict[str, int] = {}
    body_parts: list[bytes] = []

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, object]) -> None:
        if message["type"] == "http.response.start":
            status_holder["status"] = message["status"]  # type: ignore[assignment]
        elif message["type"] == "http.response.body":
            body_parts.append(message.get("body", b""))  # type: ignore[arg-type]

    await app(scope, receive, send)
    assert status_holder["status"] == 400
    body = b"".join(body_parts).decode()
    assert "Malformed fight log" in body


async def test_about_has_attribution(client) -> None:
    resp = await client.get("/about")
    assert resp.status_code == 200
    assert "not affiliated with or endorsed by Wizards of the Coast" in resp.text
