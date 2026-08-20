"""Act-endpoint tests — ``POST /play/{scenario_id}/act`` hit through a real
ASGI client.

Every test drives real scenario replays (no mocks); the "play to victory"
test greedily auto-plays a real fight using the live combat view to decide
each PC's move/attack, proving the "over" fragment path against a genuine
finished combat rather than a hand-tuned event count.
"""

from __future__ import annotations

import base64
import html
import urllib.parse
from typing import Any

import pytest
from dnd5e_engine import PlayerIntent, cell_id, parse_cell

from nat20_demo.replay import (
    MAX_ENCODED_LOG_BYTES,
    Command,
    FightLog,
    IntentCommand,
    MonsterTurnCommand,
    decode_log,
    encode_log,
    replay_fight,
)
from nat20_demo.scenarios import fresh_specs, get_scenario


@pytest.fixture
def client():
    from httpx import ASGITransport, AsyncClient

    from nat20_demo.app import create_app

    return AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://demo")


def _attack(actor: str, weapon: str, target: str) -> Command:
    return IntentCommand(
        actor=actor,
        intent=PlayerIntent(intent_type="attack", weapon_id=weapon, target_id=target),
    )


def _move(actor: str, to: str) -> Command:
    return IntentCommand(actor=actor, intent=PlayerIntent(intent_type="move", target_zone_id=to))


def _pass(actor: str) -> Command:
    return IntentCommand(actor=actor, intent=PlayerIntent(intent_type="pass"))


async def _accepted(
    scenario_id: str, seed: int, commands: list[Command], candidate: Command
) -> bool:
    """Whether ``candidate`` is both legal (no hard reject) and effective.

    A hard reject (wrong turn, etc.) surfaces as ``rejected_reason``. But a
    *legal* command can still fail for in-fiction reasons -- e.g. "move"
    beyond the turn's remaining movement budget emits a ``move_failed``
    event rather than raising -- and the autoplay loop must not treat that
    as progress or it never advances.
    """
    log = FightLog(scenario_id=scenario_id, seed=seed, commands=[*commands, candidate])
    out = await replay_fight(log, *fresh_specs(get_scenario(scenario_id)))
    if out.rejected_reason is not None:
        return False
    return not (out.delta_events and out.delta_events[-1].type.endswith("_failed"))


async def _play_to_victory(scenario_id: str, max_steps: int = 400) -> FightLog:
    """Greedily auto-play a real fight to completion (win or loss).

    Every step re-replays the accumulated log and reacts to the live view:
    monsters just advance their own turn; PCs close on the nearest living
    foe one grid-step at a time (the engine only accepts adjacent-cell
    "move" intents -- see the SHOWCASE_SCRIPTS single-step approach in
    ``test_render.py``) and attack once adjacent. Each candidate is
    speculatively replayed first and, if rejected (e.g. movement budget
    exhausted for the turn), falls back to "dodge". This is a test-only
    dumb AI, not a scenario script -- it proves the endpoint against a
    real finished combat regardless of RNG-driven outcome.
    """
    scenario = get_scenario(scenario_id)
    seed = scenario.default_seed
    commands: list[Command] = []
    for _ in range(max_steps):
        log = FightLog(scenario_id=scenario.id, seed=seed, commands=commands)
        out = await replay_fight(log, *fresh_specs(scenario))
        assert out.rejected_reason is None, out.rejected_reason
        if out.is_over:
            return log

        view = out.view
        current_id = view.initiative[view.current_turn_index % len(view.initiative)].entity_id

        if current_id not in view.party_ids:
            commands.append(MonsterTurnCommand())
            continue

        member = next(p for p in scenario.party if p.entity_id == current_id)
        living_foes = [m for m in scenario.encounter if m.entity_id not in view.dead_ids]
        my_col, my_row = parse_cell(view.actor_zone[current_id])

        def chebyshev(
            foe: object, _view: Any = view, _my_col: int = my_col, _my_row: int = my_row
        ) -> int:
            fc, fr = parse_cell(_view.actor_zone[foe.entity_id])  # type: ignore[attr-defined]
            return max(abs(fc - _my_col), abs(fr - _my_row))

        living_foes.sort(key=chebyshev)
        target = living_foes[0]
        distance_cells = chebyshev(target)
        weapon = member.equipment[0] if member.equipment else None

        candidates: list[Command] = []
        if distance_cells <= 1 and weapon:
            candidates.append(_attack(current_id, weapon, target.entity_id))
        elif weapon:
            target_col, target_row = parse_cell(view.actor_zone[target.entity_id])
            dx = max(-1, min(1, target_col - my_col))
            dy = max(-1, min(1, target_row - my_row))
            blocked = set(scenario.grid.blocked_cells)
            occupied = set(view.actor_zone.values())
            for sx, sy in ((dx, dy), (dx, 0), (0, dy)):
                if sx == 0 and sy == 0:
                    continue
                dest_col, dest_row = my_col + sx, my_row + sy
                dest = cell_id(dest_col, dest_row)
                if (
                    0 <= dest_col < scenario.grid.width
                    and 0 <= dest_row < scenario.grid.height
                    and dest not in blocked
                    and dest not in occupied
                ):
                    candidates.append(_move(current_id, dest))
        candidates.append(_pass(current_id))

        for candidate in candidates:
            if await _accepted(scenario.id, seed, commands, candidate):
                commands.append(candidate)
                break
        else:  # pragma: no cover - "pass" is always legal on your own turn
            raise AssertionError(f"no legal action found for {current_id}")

    raise AssertionError(f"{scenario_id} did not conclude within {max_steps} steps")


@pytest.fixture
def empty_log_encoded() -> str:
    scenario = get_scenario("goblin-ambush")
    return encode_log(FightLog(scenario_id=scenario.id, seed=scenario.default_seed))


async def test_act_applies_command_and_returns_fragments(client, empty_log_encoded) -> None:
    scenario = get_scenario("goblin-ambush")
    command = IntentCommand(
        actor="char:brynn", intent=PlayerIntent(intent_type="dodge")
    ).model_dump_json()

    resp = await client.post(
        f"/play/{scenario.id}/act",
        data={"seed": scenario.default_seed, "log": empty_log_encoded, "command": command},
    )
    assert resp.status_code == 200
    body = resp.text

    assert 'hx-swap-oob="true"' in body
    assert 'id="grid"' in body
    assert 'id="actions"' in body
    assert 'id="fight-log"' in body

    # New tape line (turn_started for Sera, next up) is present.
    assert "ev-turn_started" in body or "ev-round_started" in body or "Sera" in body

    # #fight-log decodes to a 1-command log.
    import re

    match = re.search(r'id="fight-log"[^>]*value="([^"]+)"', body)
    assert match is not None
    decoded = decode_log(match.group(1))
    assert len(decoded.commands) == 1


async def test_act_appends_to_existing_log(client) -> None:
    scenario = get_scenario("goblin-ambush")
    log = FightLog(
        scenario_id=scenario.id,
        seed=scenario.default_seed,
        commands=[IntentCommand(actor="char:brynn", intent=PlayerIntent(intent_type="dodge"))],
    )
    encoded = encode_log(log)
    command = IntentCommand(
        actor="char:sera", intent=PlayerIntent(intent_type="dodge")
    ).model_dump_json()

    resp = await client.post(
        f"/play/{scenario.id}/act",
        data={"seed": scenario.default_seed, "log": encoded, "command": command},
    )
    assert resp.status_code == 200

    import re

    match = re.search(r'id="fight-log"[^>]*value="([^"]+)"', resp.text)
    assert match is not None
    decoded = decode_log(match.group(1))
    assert len(decoded.commands) == 2


async def test_act_rejected_command_returns_prefix_state(client, empty_log_encoded) -> None:
    scenario = get_scenario("goblin-ambush")
    # It's Brynn's turn on an empty log -- Sera acting is a wrong-turn reject.
    command = IntentCommand(
        actor="char:sera", intent=PlayerIntent(intent_type="dodge")
    ).model_dump_json()

    resp = await client.post(
        f"/play/{scenario.id}/act",
        data={"seed": scenario.default_seed, "log": empty_log_encoded, "command": command},
    )
    assert resp.status_code == 200
    body = resp.text
    assert "rejected" in body.lower()
    assert "not_actor_turn" in body

    import re

    match = re.search(r'id="fight-log"[^>]*value="([^"]+)"', body)
    assert match is not None
    assert match.group(1) == empty_log_encoded


# A payload that would prove reflected XSS if any handler round-tripped it
# unescaped into an HTML response. Used as the attacker-controlled value in
# every negative-path test below -- these are the tests that would have
# caught the raw-f-string-HTML-assembly XSS in ``_error_fragment``. No "/"
# (would split a path-parameter route segment during ASGI routing, which is
# an unrelated routing quirk, not the vulnerability under test).
_XSS_PAYLOAD = "<img src=x onerror=alert(1)>"


async def test_act_malformed_command_400(client, empty_log_encoded) -> None:
    scenario = get_scenario("goblin-ambush")
    resp = await client.post(
        f"/play/{scenario.id}/act",
        data={
            "seed": scenario.default_seed,
            "log": empty_log_encoded,
            "command": _XSS_PAYLOAD,  # malformed JSON *and* an XSS probe
        },
    )
    assert resp.status_code == 400
    assert "Malformed command" in resp.text
    # The raw tag must never appear -- whether verbatim or via a leaked
    # pydantic ValidationError that would otherwise echo the bad input.
    assert _XSS_PAYLOAD not in resp.text
    assert "<img" not in resp.text
    assert "onerror=" not in resp.text


async def test_act_oversized_log_400(client) -> None:
    scenario = get_scenario("goblin-ambush")
    log = FightLog(
        scenario_id=scenario.id,
        seed=scenario.default_seed,
        commands=[MonsterTurnCommand()] * 500,
    )
    encoded = encode_log(log)
    # The command must be well-formed here -- command parsing happens
    # *before* the cap check, so a malformed command would 400 on that
    # earlier branch instead of proving this one. There's no natural
    # attacker-reflected string on this path (the message is purely
    # numeric), but assert on it anyway as a content regression guard.
    command = MonsterTurnCommand().model_dump_json()
    resp = await client.post(
        f"/play/{scenario.id}/act",
        data={"seed": scenario.default_seed, "log": encoded, "command": command},
    )
    assert resp.status_code == 400
    assert "too large" in resp.text.lower()
    assert "500" in resp.text  # the cap, surfaced from LogTooLargeError's message
    assert _XSS_PAYLOAD not in resp.text


async def test_act_malformed_log_400(client) -> None:
    scenario = get_scenario("goblin-ambush")
    command = MonsterTurnCommand().model_dump_json()
    # Valid base64 that decodes to garbage JSON containing the XSS probe --
    # this is exactly the shape that leaked through pydantic's
    # ValidationError text (which echoes the raw decoded payload via
    # "input_value=...") before the fix.
    poisoned_log = base64.urlsafe_b64encode(_XSS_PAYLOAD.encode()).decode()

    resp = await client.post(
        f"/play/{scenario.id}/act",
        data={"seed": scenario.default_seed, "log": poisoned_log, "command": command},
    )
    assert resp.status_code == 400
    assert "Malformed fight log" in resp.text
    assert _XSS_PAYLOAD not in resp.text
    assert "<img" not in resp.text
    assert "onerror=" not in resp.text

    # Also cover the not-even-base64 shape.
    resp2 = await client.post(
        f"/play/{scenario.id}/act",
        data={"seed": scenario.default_seed, "log": "!!!not-b64", "command": command},
    )
    assert resp2.status_code == 400
    assert "Malformed fight log" in resp2.text


async def test_act_oversized_raw_log_400(client) -> None:
    """A huge, not-even-base64 ``log`` value is rejected on ``len()`` alone
    (the size guard in ``decode_log`` runs before any decode work) -- distinct
    from ``test_act_oversized_log_400`` above, which exercises the
    ``MAX_COMMANDS`` cap on a well-formed, legitimately encoded log.
    """
    scenario = get_scenario("goblin-ambush")
    huge = "A" * (MAX_ENCODED_LOG_BYTES + 1)
    command = MonsterTurnCommand().model_dump_json()
    resp = await client.post(
        f"/play/{scenario.id}/act",
        data={"seed": scenario.default_seed, "log": huge, "command": command},
    )
    assert resp.status_code == 400
    assert "Malformed fight log" in resp.text


async def test_act_unknown_scenario_404(client, empty_log_encoded) -> None:
    command = MonsterTurnCommand().model_dump_json()
    scenario_id = _XSS_PAYLOAD
    resp = await client.post(
        f"/play/{urllib.parse.quote(scenario_id, safe='')}/act",
        data={"seed": 1, "log": empty_log_encoded, "command": command},
    )
    assert resp.status_code == 404
    assert "Unknown scenario" in resp.text
    # The 404 message legitimately echoes scenario_id back (e.g. `No
    # scenario named "..."`) -- that's fine as long as the reflection is
    # HTML-escaped. The regression this guards against is the raw `<img`
    # tag delimiter surviving unescaped (which would let the browser parse
    # it as markup); `onerror=` alone, safely trapped inside an escaped
    # `&lt;img ... &gt;` text node, is inert and not what's being tested.
    assert _XSS_PAYLOAD not in resp.text
    assert "<img" not in resp.text
    assert html.escape(scenario_id) in resp.text


async def test_act_after_combat_over_shows_outcome(client) -> None:
    winning_log = await _play_to_victory("goblin-ambush")
    scenario = get_scenario("goblin-ambush")
    encoded = encode_log(winning_log)
    # Trailing command is unreachable (fight already over) -- still a legal
    # POST, and the endpoint must still show the outcome card.
    command = MonsterTurnCommand().model_dump_json()

    resp = await client.post(
        f"/play/{scenario.id}/act",
        data={"seed": scenario.default_seed, "log": encoded, "command": command},
    )
    assert resp.status_code == 200
    body = resp.text
    assert "Fight over" in body
    assert "Play again" in body
