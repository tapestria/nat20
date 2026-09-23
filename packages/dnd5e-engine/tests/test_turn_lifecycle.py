"""F3a — turn-boundary lifecycle hooks + ``TurnPhase`` markers.

Before F3a the engine had three hand-copied turn-advance blocks
(``start_combat``'s opening emit, ``_advance_turn``, and the tail of
``advance_monster_turn``) and no seam at which a rule could say "at the start
of your turn" / "at the end of your turn". ``dnd5e_engine.turn_lifecycle``
adds that seam and ``_end_turn_and_advance`` collapses the three copies into
one path.

These tests pin the three things later clusters (ongoing damage, regeneration,
recharge, legendary-action reset, timed expiry) will depend on:

1. hooks fire once per boundary, with the right actor, in registration order;
2. the event order around a boundary is fixed;
3. the registry survives a hook that mutates it mid-run.

Plus a guard that the two hooks the orchestrator moved into the registry
(duration tick, reaction-effect expiry) still behave exactly as before — the
duration-tick behaviour itself is covered by
``tests/test_duration_tick_at_turn_end.py``.
"""

from __future__ import annotations

import asyncio

import pytest

from dnd5e_engine import PlayerIntent
from dnd5e_engine.events import TurnPhase
from dnd5e_engine.orchestrator import (
    _get_live,
    advance_monster_turn,
    start_combat,
    submit_player_intent,
)
from dnd5e_engine.specs import EncounterMemberSpec, PartyMemberSpec, SceneTopology
from dnd5e_engine.turn_lifecycle import TurnLifecycle


def _party():
    return [
        PartyMemberSpec(
            entity_id="char:hero",
            name="Hero",
            initiative=20,
            hp_current=20,
            hp_max=20,
            zone_id="zone:start",
        ),
    ]


def _encounter():
    return [
        EncounterMemberSpec(
            entity_id="mon:foe",
            entity_type="Monster",
            name="Foe",
            initiative=10,
            hp_current=11,
            hp_max=11,
            zone_id="zone:start",
        ),
    ]


def _topology():
    return SceneTopology(zones=["zone:start"], edges=[])


async def _start(session_id: str):
    return await start_combat(
        session_id=session_id,
        party=_party(),
        encounter=_encounter(),
        scene_zones=_topology(),
        rng_seed=7,
    )


def _phase_trace(live) -> list[tuple[str, str | None]]:
    return [(e.phase, e.actor_id) for e in live.event_log if isinstance(e, TurnPhase)]


# ── the registry in isolation ───────────────────────────────────────────────


class _FakeLive:
    """Stand-in for ``_LiveCombat`` — the registry only ever passes it through."""


def test_hooks_run_in_registration_order():
    """Execution order is registration order, not dict/set order — the
    determinism contract every seeded replay leans on."""
    lifecycle = TurnLifecycle()
    calls: list[str] = []
    for name in ("c", "a", "b"):
        lifecycle.register("turn_start", lambda _live, _actor, n=name: calls.append(n), key=name)
    lifecycle.run(_FakeLive(), "turn_start", "char:hero")
    assert calls == ["c", "a", "b"]


def test_hooks_are_isolated_per_phase():
    """A hook registered for one phase never fires for another."""
    lifecycle = TurnLifecycle()
    calls: list[tuple[str, str | None]] = []
    lifecycle.register("turn_end", lambda _l, actor: calls.append(("end", actor)), key="end")
    lifecycle.register("round_start", lambda _l, actor: calls.append(("round", actor)), key="round")
    live = _FakeLive()
    lifecycle.run(live, "turn_start", "char:hero")
    assert calls == []
    lifecycle.run(live, "turn_end", "char:hero")
    lifecycle.run(live, "round_start", None)
    assert calls == [("end", "char:hero"), ("round", None)]


def test_hook_may_unregister_itself_during_run():
    """A one-shot hook that retires itself mid-run must not corrupt the
    iteration — ``run`` walks a snapshot — and must not fire again."""
    lifecycle = TurnLifecycle()
    calls: list[str] = []

    def once(_live, _actor) -> None:
        calls.append("once")
        lifecycle.unregister("once")

    lifecycle.register("turn_start", once, key="once")
    lifecycle.register("turn_start", lambda _l, _a: calls.append("after"), key="after")

    live = _FakeLive()
    lifecycle.run(live, "turn_start", "char:hero")
    # Both ran on the first pass despite the mid-run mutation.
    assert calls == ["once", "after"]
    lifecycle.run(live, "turn_start", "char:hero")
    assert calls == ["once", "after", "after"]


def test_duplicate_key_is_rejected():
    """Shadowing a key would make run order depend on import order."""
    lifecycle = TurnLifecycle()
    lifecycle.register("turn_start", lambda _l, _a: None, key="dup")
    with pytest.raises(ValueError, match="already registered"):
        lifecycle.register("turn_end", lambda _l, _a: None, key="dup")
    # After retiring it the key is free again.
    lifecycle.unregister("dup")
    lifecycle.register("turn_end", lambda _l, _a: None, key="dup")


def test_unregister_unknown_key_is_a_noop():
    TurnLifecycle().unregister("never-registered")


def test_unknown_phase_is_rejected():
    with pytest.raises(ValueError, match="unknown turn phase"):
        TurnLifecycle().register("mid_turn", lambda _l, _a: None, key="x")  # type: ignore[arg-type]


# ── wired into a live combat ────────────────────────────────────────────────


def test_turn_start_hook_fires_once_per_turn_with_the_incoming_actor():
    """Hero (init 20) passes, foe takes its turn: the hook sees the foe on the
    first boundary and the hero again when the round wraps."""

    async def _run():
        start = await _start("sess-lifecycle-start")
        live = _get_live(start.handle)
        seen: list[str | None] = []
        live.lifecycle.register("turn_start", lambda _l, actor: seen.append(actor), key="test:seen")
        await submit_player_intent(
            start.handle, actor_id="char:hero", intent=PlayerIntent(intent_type="pass")
        )
        await advance_monster_turn(start.handle)
        return seen

    # Registered after start_combat, so the opening turn_start is not counted.
    assert asyncio.run(_run()) == ["mon:foe", "char:hero"]


def test_turn_end_hook_fires_with_the_outgoing_actor():
    async def _run():
        start = await _start("sess-lifecycle-end")
        live = _get_live(start.handle)
        seen: list[str | None] = []
        live.lifecycle.register("turn_end", lambda _l, actor: seen.append(actor), key="test:seen")
        await submit_player_intent(
            start.handle, actor_id="char:hero", intent=PlayerIntent(intent_type="pass")
        )
        await advance_monster_turn(start.handle)
        return seen

    assert asyncio.run(_run()) == ["char:hero", "mon:foe"]


def test_round_start_hook_fires_once_on_the_wrap_with_no_actor():
    """One combat round = two turns here; ``round_start`` fires only on wrap.
    ``start_combat``'s opening round is not counted (registration is later)."""

    async def _run():
        start = await _start("sess-lifecycle-round")
        live = _get_live(start.handle)
        seen: list[str | None] = []
        live.lifecycle.register(
            "round_start", lambda _l, actor: seen.append(actor), key="test:seen"
        )
        await submit_player_intent(
            start.handle, actor_id="char:hero", intent=PlayerIntent(intent_type="pass")
        )
        assert seen == []  # mid-round: hero -> foe, no wrap
        await advance_monster_turn(start.handle)
        return seen, live.round_number

    seen, round_number = asyncio.run(_run())
    assert seen == [None]
    assert round_number == 2


def test_turn_phase_markers_bracket_the_boundary_in_a_fixed_order():
    """The F3a event-order contract, pinned end to end.

    ``start_combat`` opens with round_start + turn_start (no turn to end);
    each subsequent boundary is turn_end -> TurnEnded -> [RoundStarted +
    round_start on wrap] -> TurnStarted -> turn_start.
    """

    async def _run():
        start = await _start("sess-lifecycle-order")
        await submit_player_intent(
            start.handle, actor_id="char:hero", intent=PlayerIntent(intent_type="pass")
        )
        await advance_monster_turn(start.handle)
        return _get_live(start.handle)

    live = asyncio.run(_run())

    assert _phase_trace(live) == [
        # start_combat
        ("round_start", None),
        ("turn_start", "char:hero"),
        # hero passes -> foe
        ("turn_end", "char:hero"),
        ("turn_start", "mon:foe"),
        # foe acts -> wrap to round 2 -> hero
        ("turn_end", "mon:foe"),
        ("round_start", None),
        ("turn_start", "char:hero"),
    ]

    # Interleaving with the structural events, on the wrapping boundary: slice
    # the log from the last turn_end marker (the foe's) and read forwards.
    last_turn_end = max(
        i
        for i, e in enumerate(live.event_log)
        if isinstance(e, TurnPhase) and e.phase == "turn_end"
    )
    wrap = [e.type for e in live.event_log[last_turn_end:]]
    assert wrap[:6] == [
        "turn_phase",  # turn_end, mon:foe
        "turn_ended",
        "round_started",
        "turn_phase",  # round_start
        "turn_started",
        "turn_phase",  # turn_start, char:hero
    ]

    # Round numbers are the round the phase belongs to: the turn_end marker
    # carries the round that is ending, the round_start pair the new one.
    markers = [e for e in live.event_log if isinstance(e, TurnPhase)]
    assert [(m.phase, m.round_number) for m in markers[-3:]] == [
        ("turn_end", 1),
        ("round_start", 2),
        ("turn_start", 2),
    ]


def test_hooks_registered_by_the_engine_are_present_and_ordered():
    """The two pre-F3a inline blocks are now registered hooks, joined by F3b's
    timed-effect expiry and the F3a-follow-up repeat save. Registration order is
    part of the seeded-replay contract, so it is pinned here:

    * ``engine:repeat-save`` must stay FIRST — the SRD end-of-turn repeat save
      (Hold Person & co.) has to resolve while its source effect is still live,
      i.e. before ``engine:duration-tick`` could expire that effect on the same
      boundary;
    * ``engine:timed-effect-expiry`` must stay AFTER ``engine:duration-tick``
      (the round tick claims an effect's ``rounds`` counter before the seconds
      branch can look at it);
    * ``engine:concentration-expiry`` (C13) must stay LAST among the pre-C15
      hooks — a same-boundary repeat save must still roll against a live
      effect before the concentration cap can cascade its own drop.
    * ``engine:vex-expiry`` (C15 Task 6, SRD §Weapon Mastery / Vex) is
      appended AFTER concentration-expiry — it decrements independent
      per-attacker mastery-grant counters with no cross-hook ordering
      dependency, so it only needs to run once per turn end, after the
      others.
    """

    async def _run():
        start = await _start("sess-lifecycle-defaults")
        live = _get_live(start.handle)
        return {phase: [key for key, _ in hooks] for phase, hooks in live.lifecycle._hooks.items()}

    assert asyncio.run(_run()) == {
        "round_start": [],
        "turn_start": ["engine:reaction-effect-expiry"],
        "turn_end": [
            "engine:repeat-save",
            "engine:duration-tick",
            "engine:timed-effect-expiry",
            "engine:concentration-expiry",
            "engine:vex-expiry",
        ],
    }
