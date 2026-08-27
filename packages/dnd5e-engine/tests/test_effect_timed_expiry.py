"""F3b — timed effect expiry: ``seconds``, ``turns``, until-end-of-next-turn.

Before F3b only ``ActiveEffectDuration.rounds`` ticked (at the CASTER's turn
end, ``_tick_durations_at_turn_end``); ``seconds`` and ``turns`` were carried
by the schema and read by nobody, so a Foundry pack effect whose duration is
expressed in seconds (the majority — see
``packages/dnd5e-srd-data/.../canonical/spells/*.json``) never expired inside a
combat. F3b adds ONE ``turn_end`` hook (``_hook_expire_timed_effects``,
registered after the round tick) that owns the three remaining duration
shapes:

* ``seconds``     — SRD 5.2 §Duration: a round is 6 seconds, so ``seconds`` is
  ``ceil(seconds / 6)`` rounds, ticked exactly like ``rounds`` (caster-keyed).
* ``turns``       — decremented at the TARGET's own turn end.
* ``flags["until_end_of_next_turn_of"]`` — expires at that actor's next turn
  end ("until the end of your next turn").

Concentration-flagged effects stay exempt from every branch (the concentration
cascade owns their lifetime — see ``test_duration_tick_at_turn_end``).
"""

from __future__ import annotations

import asyncio
from typing import Any

from dnd5e_engine import PlayerIntent
from dnd5e_engine.events import EffectApplied, EffectExpired, TurnEnded, TurnStarted
from dnd5e_engine.orchestrator import (
    _emit,
    _get_live,
    advance_monster_turn,
    start_combat,
    submit_player_intent,
)
from dnd5e_engine.specs import (
    EncounterMemberSpec,
    PartyMemberSpec,
    SceneTopology,
)
from dnd5e_engine.types.effects import (
    ActiveEffect,
    ActiveEffectDuration,
)


def _party() -> list[PartyMemberSpec]:
    return [
        PartyMemberSpec(
            entity_id="char:hero",
            name="Hero",
            initiative=15,
            hp_current=40,
            hp_max=40,
            zone_id="zone:start",
        ),
    ]


def _encounter() -> list[EncounterMemberSpec]:
    return [
        EncounterMemberSpec(
            entity_id="mon:foe",
            entity_type="Monster",
            name="Foe",
            initiative=10,
            hp_current=30,
            hp_max=30,
            zone_id="zone:start",
        ),
    ]


def _topology() -> SceneTopology:
    return SceneTopology(zones=["zone:start"], edges=[])


async def _start(session_id: str, effects: tuple[ActiveEffect, ...]) -> Any:
    return await start_combat(
        session_id=session_id,
        party=_party(),
        encounter=_encounter(),
        scene_zones=_topology(),
        rng_seed=1,
        active_effects=effects,
    )


async def _hero_turn(handle: Any) -> None:
    await submit_player_intent(
        handle, actor_id="char:hero", intent=PlayerIntent(intent_type="pass")
    )


async def _foe_turn(handle: Any) -> None:
    await advance_monster_turn(handle)


def _effects_of(live: Any, target_id: str) -> list[ActiveEffect]:
    return list(live.active_effects.get(target_id, []))


# ── (a) turns → the TARGET's turn end ────────────────────────────────


def test_turns_tick_at_target_turn_end_not_caster() -> None:
    """``turns=1`` on B, cast by A, survives A's turn end and expires at B's."""

    async def _run() -> Any:
        eff = ActiveEffect(
            id="effect:hexed",
            name="Hexed",
            origin="cast:hex:char:hero",  # caster is the HERO
            target_id="mon:foe",  # target is the FOE
            duration=ActiveEffectDuration(turns=1),
            flags={"concentration": False},
        )
        start = await _start("sess-turns", (eff,))
        live = _get_live(start.handle)
        await _hero_turn(start.handle)  # caster's turn end — no tick
        assert _effects_of(live, "mon:foe"), "turns must not tick at the caster's turn end"
        assert _effects_of(live, "mon:foe")[0].duration.turns == 1
        await _foe_turn(start.handle)  # target's turn end — 1 → 0 → expire
        return live

    live = asyncio.run(_run())
    assert not _effects_of(live, "mon:foe")
    expired = [e for e in live.event_log if isinstance(e, EffectExpired)]
    assert [(e.effect_id, e.target_id, e.reason) for e in expired] == [
        ("effect:hexed", "mon:foe", "duration")
    ]


def test_turns_multi_decrements_once_per_target_turn() -> None:
    """``turns=2`` needs two of the target's own turn ends."""

    async def _run() -> Any:
        eff = ActiveEffect(
            id="effect:hexed",
            name="Hexed",
            origin="cast:hex:char:hero",
            target_id="mon:foe",
            duration=ActiveEffectDuration(turns=2),
            flags={"concentration": False},
        )
        start = await _start("sess-turns-2", (eff,))
        live = _get_live(start.handle)
        await _hero_turn(start.handle)
        await _foe_turn(start.handle)
        assert _effects_of(live, "mon:foe")[0].duration.turns == 1
        await _hero_turn(start.handle)
        await _foe_turn(start.handle)
        return live

    live = asyncio.run(_run())
    assert not _effects_of(live, "mon:foe")


def test_turns_exempt_for_concentration_effects() -> None:
    """Concentration-flagged effects ignore the ``turns`` counter (C13 owns them)."""

    async def _run() -> Any:
        eff = ActiveEffect(
            id="effect:stinking-poison",
            name="Stinking Poison",
            origin="cast:stinking-cloud:char:hero",
            target_id="mon:foe",
            duration=ActiveEffectDuration(turns=1),
            flags={"concentration": True},
        )
        start = await _start("sess-turns-conc", (eff,))
        live = _get_live(start.handle)
        await _hero_turn(start.handle)
        await _foe_turn(start.handle)
        return live

    live = asyncio.run(_run())
    assert _effects_of(live, "mon:foe")
    assert _effects_of(live, "mon:foe")[0].duration.turns == 1


# ── (b) seconds → ceil(seconds / 6) rounds, caster-keyed ─────────────


def test_seconds_twelve_behaves_as_two_rounds() -> None:
    """``seconds=12`` == ``rounds=2``: survives one caster turn end, dies at the second."""

    async def _run() -> Any:
        eff = ActiveEffect(
            id="effect:timed",
            name="Timed",
            origin="cast:timed:char:hero",
            target_id="char:hero",
            duration=ActiveEffectDuration(seconds=12),
            flags={"concentration": False},
        )
        start = await _start("sess-seconds", (eff,))
        live = _get_live(start.handle)
        await _hero_turn(start.handle)  # round 1 caster turn end: 2 → 1
        assert _effects_of(live, "char:hero"), "12s must outlive one caster turn end"
        assert _effects_of(live, "char:hero")[0].duration.rounds == 1
        assert _effects_of(live, "char:hero")[0].duration.seconds == 12
        await _foe_turn(start.handle)
        assert _effects_of(live, "char:hero"), "the foe's turn end must not tick it"
        await _hero_turn(start.handle)  # round 2 caster turn end: 1 → 0
        return live

    live = asyncio.run(_run())
    assert not _effects_of(live, "char:hero")
    expired = [e for e in live.event_log if isinstance(e, EffectExpired)]
    assert [(e.effect_id, e.reason) for e in expired] == [("effect:timed", "duration")]


def test_seconds_six_expires_at_first_caster_turn_end() -> None:
    """``seconds=6`` == ``rounds=1`` (and ``ceil`` rounds 7s up to 2 rounds)."""

    async def _run() -> Any:
        one = ActiveEffect(
            id="effect:six",
            name="Six",
            origin="cast:six:char:hero",
            target_id="char:hero",
            duration=ActiveEffectDuration(seconds=6),
            flags={"concentration": False},
        )
        two = ActiveEffect(
            id="effect:seven",
            name="Seven",
            origin="cast:seven:char:hero",
            target_id="char:hero",
            duration=ActiveEffectDuration(seconds=7),
            flags={"concentration": False},
        )
        start = await _start("sess-seconds-ceil", (one, two))
        live = _get_live(start.handle)
        await _hero_turn(start.handle)
        return live

    live = asyncio.run(_run())
    remaining = {eff.id: eff for eff in _effects_of(live, "char:hero")}
    assert set(remaining) == {"effect:seven"}
    assert remaining["effect:seven"].duration.rounds == 1


def test_seconds_sixty_expires_at_the_casters_tenth_turn_end() -> None:
    """``seconds=60`` — one minute, the most common duration in the pack corpus —
    is ``ceil(60 / 6) = 10`` rounds: present after the caster's 9th turn end,
    gone at the 10th, and never at the 11th (it is already gone).

    Walks the whole chain because the first tick is the odd one out: the
    seconds branch materialises ``rounds=9`` and decrements in the same pass,
    after which the pre-existing round tick owns the counter. An off-by-one in
    that hand-off would only ever show up at the far end.
    """

    async def _run() -> Any:
        eff = ActiveEffect(
            id="effect:minute",
            name="One Minute",
            origin="cast:minute:char:hero",
            target_id="char:hero",
            duration=ActiveEffectDuration(seconds=60),
            flags={"concentration": False},
        )
        start = await _start("sess-seconds-60", (eff,))
        live = _get_live(start.handle)
        for turn_ends in range(1, 10):
            await _hero_turn(start.handle)  # the caster's Nth turn end
            remaining = _effects_of(live, "char:hero")
            assert remaining, f"1 minute must outlive the caster's turn end #{turn_ends}"
            # 10 rounds total: the Nth caster turn end leaves 10 - N.
            assert remaining[0].duration.rounds == 10 - turn_ends
            assert remaining[0].duration.seconds == 60
            await _foe_turn(start.handle)
            assert _effects_of(live, "char:hero"), "the foe's turn end must not tick it"
        await _hero_turn(start.handle)  # the caster's 10th turn end
        return live

    live = asyncio.run(_run())
    assert not _effects_of(live, "char:hero")
    expired = [e for e in live.event_log if isinstance(e, EffectExpired)]
    assert [(e.effect_id, e.reason) for e in expired] == [("effect:minute", "duration")]
    hero_ends = [
        i
        for i, e in enumerate(live.event_log)
        if isinstance(e, TurnEnded) and e.actor_id == "char:hero"
    ]
    assert len(hero_ends) == 10
    # Fired inside the 10th turn-end hook run: after the 9th TurnEnded, before
    # the 10th (turn_end hooks run ahead of the TurnEnded event).
    idx = live.event_log.index(expired[0])
    assert hero_ends[8] < idx < hero_ends[9]


def test_seconds_exempt_for_concentration_effects() -> None:
    """Hunter's Mark (``seconds=600``, concentration) is untouched by the hook."""

    async def _run() -> Any:
        eff = ActiveEffect(
            id="effect:hunters-mark",
            name="Hunter's Mark",
            origin="cast:hunters-mark:char:hero",
            target_id="mon:foe",
            duration=ActiveEffectDuration(seconds=600),
            flags={"concentration": True},
        )
        start = await _start("sess-seconds-conc", (eff,))
        live = _get_live(start.handle)
        await _hero_turn(start.handle)
        return live

    live = asyncio.run(_run())
    assert _effects_of(live, "mon:foe")[0].duration.rounds is None


# ── (e) rounds AND seconds → rounds wins ─────────────────────────────


def test_rounds_wins_over_seconds() -> None:
    """Bless ships ``rounds=10`` + ``seconds=60``: the 10-round counter governs."""

    async def _run() -> Any:
        eff = ActiveEffect(
            id="effect:blessed",
            name="Blessed",
            origin="cast:bless:char:hero",
            target_id="char:hero",
            duration=ActiveEffectDuration(rounds=10, seconds=60),
            flags={"concentration": False},
        )
        start = await _start("sess-rounds-wins", (eff,))
        live = _get_live(start.handle)
        await _hero_turn(start.handle)
        return live

    live = asyncio.run(_run())
    survivor = _effects_of(live, "char:hero")[0]
    # One tick only — the existing rounds tick. Had the seconds branch also
    # fired, ceil(60/6)=10 would have been re-materialised (or double-ticked).
    assert survivor.duration.rounds == 9
    assert survivor.duration.seconds == 60


def test_short_seconds_never_shortens_a_longer_rounds_counter() -> None:
    """``rounds=10`` + ``seconds=6`` must NOT expire after one caster turn end."""

    async def _run() -> Any:
        eff = ActiveEffect(
            id="effect:mixed",
            name="Mixed",
            origin="cast:mixed:char:hero",
            target_id="char:hero",
            duration=ActiveEffectDuration(rounds=10, seconds=6),
            flags={"concentration": False},
        )
        start = await _start("sess-mixed", (eff,))
        live = _get_live(start.handle)
        await _hero_turn(start.handle)
        return live

    live = asyncio.run(_run())
    assert _effects_of(live, "char:hero")[0].duration.rounds == 9


# ── (c) until_end_of_next_turn_of ────────────────────────────────────


def test_until_end_of_next_turn_expires_at_that_actors_turn_end() -> None:
    """Applied outside the named actor's turn → dies at that actor's very next
    turn end, and no earlier (the hero's turn end in between leaves it alone)."""

    async def _run() -> Any:
        eff = ActiveEffect(
            id="effect:marked",
            name="Marked",
            origin="cast:marked:char:hero",
            target_id="char:hero",
            duration=ActiveEffectDuration(),
            flags={"until_end_of_next_turn_of": "mon:foe"},
        )
        start = await _start("sess-ueont", (eff,))
        live = _get_live(start.handle)
        await _hero_turn(start.handle)
        assert _effects_of(live, "char:hero"), "must survive an unrelated actor's turn end"
        await _foe_turn(start.handle)
        return live

    live = asyncio.run(_run())
    assert not _effects_of(live, "char:hero")
    expired = [e for e in live.event_log if isinstance(e, EffectExpired)]
    assert [(e.effect_id, e.target_id, e.reason) for e in expired] == [
        ("effect:marked", "char:hero", "duration")
    ]


def test_until_end_of_next_turn_applied_during_own_turn_survives_that_turn() -> None:
    """ "Until the end of your NEXT turn": applied during the actor's own turn,
    it survives that turn's end and expires one turn later."""

    async def _run() -> Any:
        start = await _start("sess-ueont-own", ())
        live = _get_live(start.handle)
        await _hero_turn(start.handle)  # now it is the foe's turn
        eff = ActiveEffect(
            id="effect:marked",
            name="Marked",
            origin="cast:marked:mon:foe",
            target_id="char:hero",
            duration=ActiveEffectDuration(),
            flags={"until_end_of_next_turn_of": "mon:foe"},
        )
        _emit(live, EffectApplied(effect=eff))
        await _foe_turn(start.handle)  # the foe's CURRENT turn ends — survives
        assert _effects_of(live, "char:hero"), "must survive the turn it was applied on"
        await _hero_turn(start.handle)
        assert _effects_of(live, "char:hero")
        await _foe_turn(start.handle)  # the foe's NEXT turn ends — expires
        return live

    live = asyncio.run(_run())
    assert not _effects_of(live, "char:hero")


# ── (d) F3a regression — reaction Shield still dies at turn START ────


def test_reaction_effect_still_expires_at_owner_turn_start() -> None:
    """Shield-shaped reaction buffs keep the F3a semantics: the owner's next
    turn START, not their turn end.

    The full reaction path is pinned by
    ``tests/e2e/test_c06_reactions.py::test_c06_s03_...``; this seeds the same
    ``reaction_effects_pending_expiry`` entry the reaction cast writes, so the
    new ``turn_end`` hook is proven not to steal the expiry.
    """

    async def _run() -> Any:
        start = await _start("sess-shield", ())
        live = _get_live(start.handle)
        await _hero_turn(start.handle)  # the reaction fires on the FOE's turn
        shield = ActiveEffect(
            id="effect:imperceptible-barrier",
            name="Imperceptible Barrier",
            origin="cast:shield:char:hero",
            target_id="char:hero",
            duration=ActiveEffectDuration(rounds=1),
            flags={"concentration": False},
        )
        _emit(live, EffectApplied(effect=shield))
        live.reaction_effects_pending_expiry.setdefault("char:hero", []).append(
            ("char:hero", shield.id, shield.origin)
        )
        await _foe_turn(start.handle)  # wraps into round 2 -> hero's turn STARTS
        return live

    live = asyncio.run(_run())
    assert not _effects_of(live, "char:hero")
    expired = [e for e in live.event_log if isinstance(e, EffectExpired)]
    assert len(expired) == 1
    idx = live.event_log.index(expired[0])
    starts = [
        i
        for i, e in enumerate(live.event_log)
        if isinstance(e, TurnStarted) and e.actor_id == "char:hero"
    ]
    ends = [
        i
        for i, e in enumerate(live.event_log)
        if isinstance(e, TurnEnded) and e.actor_id == "char:hero"
    ]
    # Fires just after the hero's SECOND TurnStarted (round 2), never at a
    # turn end: a turn-end expiry would land before that TurnStarted.
    assert len(ends) == 1
    assert idx > starts[1] > ends[0]
