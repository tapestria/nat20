"""Replay-core tests — the determinism / prefix-composition proof.

The whole demo architecture rests on one property: a ``FightLog`` is the
only state, and replaying it reproduces the same combat byte-for-byte.
These tests are that proof; never weaken them to make a change pass.
"""

from __future__ import annotations

from typing import Any

import pytest
from dnd5e_engine import (
    CombatEvent,
    EncounterMemberSpec,
    GridScene,
    PartyMemberSpec,
    PlayerIntent,
    cell_id,
)

from nat20_demo.replay import (
    Command,
    FightLog,
    IntentCommand,
    LogTooLargeError,
    MonsterTurnCommand,
    decode_log,
    encode_log,
    replay_fight,
)


def fresh_specs() -> tuple[list[PartyMemberSpec], list[EncounterMemberSpec], GridScene]:
    """Newly constructed spec models on every call (never shared across replays)."""
    party = [
        PartyMemberSpec(
            entity_id="char:hero",
            name="Hero",
            initiative=20,
            hp_current=20,
            hp_max=20,
            ac=12,
            attack_bonus=5,
            zone_id=cell_id(0, 0),
            equipment=("longsword",),
        )
    ]
    encounter = [
        EncounterMemberSpec(
            entity_id="mon:gob",
            entity_type="Monster",
            name="Goblin Warrior",
            monster_template_slug="goblin-warrior",
            initiative=1,
            # SRD goblin-warrior HP is 7, but a single longsword hit ends the
            # fight — which would make the prefix / delta proofs below vacuous.
            # This is a test dummy, not a scenario: give it enough HP that the
            # 5-command SCRIPT actually plays out over several turns.
            hp_current=30,
            hp_max=30,
            ac=13,
            zone_id=cell_id(1, 0),
            xp_value=50,
        )
    ]
    return party, encounter, GridScene(width=6, height=6)


def hero_attack() -> Command:
    return IntentCommand(
        actor="char:hero",
        # weapon_id is required for the attack to resolve through the typed
        # weapon activity (mirrors the engine's own grid-combat tests).
        intent=PlayerIntent(intent_type="attack", weapon_id="longsword", target_id="mon:gob"),
    )


def make_log(commands: list[Command], seed: int = 1337) -> FightLog:
    return FightLog(scenario_id="test", seed=seed, commands=list(commands))


SCRIPT: list[Command] = [
    hero_attack(),
    MonsterTurnCommand(),
    hero_attack(),
    MonsterTurnCommand(),
    hero_attack(),
]


def dumps(events: list[CombatEvent]) -> list[dict[str, Any]]:
    """Comparable, order-preserving projection of an event stream."""
    return [e.model_dump() for e in events]


CLOSE_EVENT_TYPES = frozenset({"combat_ended"})


def core(events: list[CombatEvent]) -> list[dict[str, Any]]:
    """Event dumps with the trailing close events (CombatEnded) dropped.

    A replay whose fight is already over folds ``end_combat``'s close events
    onto the tail of its stream; a longer replay of the same script emits the
    identical open+command events and only then its own close events. The
    prefix property is therefore stated over the open+command portion.
    """
    dumped = dumps(events)
    while dumped and dumped[-1]["type"] in CLOSE_EVENT_TYPES:
        dumped.pop()
    return dumped


async def test_prefix_replays_compose() -> None:
    """Replaying commands[:i] yields a prefix of replaying commands[:i+1]."""
    prev: list[dict[str, Any]] = []
    saw_growth = False
    for i in range(len(SCRIPT) + 1):
        out = await replay_fight(make_log(SCRIPT[:i]), *fresh_specs())
        assert out.rejected_reason is None, f"prefix {i} rejected: {out.rejected_reason}"
        current = core(out.all_events)
        assert len(current) >= len(prev), f"prefix {i} shrank the event stream"
        divergence = next(
            (j for j in range(len(prev)) if current[j] != prev[j]),
            None,
        )
        assert divergence is None, (
            f"prefix {i - 1} is not a prefix of prefix {i}; first divergence at "
            f"index {divergence}:\n  short={prev[divergence]}\n  long ={current[divergence]}"
        )
        saw_growth = saw_growth or len(current) > len(prev)
        prev = current
    assert saw_growth, "no prefix ever added events — the script resolved nothing"


async def test_same_log_twice_is_identical() -> None:
    a = await replay_fight(make_log(SCRIPT[:3]), *fresh_specs())
    b = await replay_fight(make_log(SCRIPT[:3]), *fresh_specs())
    assert dumps(a.all_events) == dumps(b.all_events)
    assert a.view.tracked_hp == b.view.tracked_hp


async def test_different_seed_diverges() -> None:
    a = await replay_fight(make_log(SCRIPT[:1], seed=1337), *fresh_specs())
    b = await replay_fight(make_log(SCRIPT[:1], seed=1338), *fresh_specs())
    assert dumps(a.all_events) != dumps(b.all_events)  # attack roll totals differ


async def test_delta_is_last_command_events() -> None:
    two = await replay_fight(make_log(SCRIPT[:2]), *fresh_specs())
    one = await replay_fight(make_log(SCRIPT[:1]), *fresh_specs())
    assert dumps(one.all_events) + dumps(two.delta_events) == dumps(two.all_events)


async def test_rejected_command_stops_at_prefix() -> None:
    # Hero acts on the goblin's turn: command 1 is a second hero intent right
    # after `hero_attack()` already ended the hero's turn.
    out = await replay_fight(make_log([hero_attack(), hero_attack()]), *fresh_specs())
    assert out.accepted == 1
    assert out.rejected_reason is not None
    assert "not_actor_turn" in out.rejected_reason


async def test_empty_log_renders_opening_state() -> None:
    out = await replay_fight(make_log([]), *fresh_specs())
    assert out.accepted == 0
    assert not out.is_over
    assert any(e.type == "round_started" for e in out.all_events)
    assert out.delta_events == out.all_events


async def test_log_cap_enforced() -> None:
    with pytest.raises(LogTooLargeError):
        await replay_fight(make_log([MonsterTurnCommand()] * 501), *fresh_specs())


def test_encode_decode_roundtrip() -> None:
    log = make_log(SCRIPT[:2])
    assert decode_log(encode_log(log)) == log


def test_decode_garbage_raises() -> None:
    with pytest.raises(ValueError):
        decode_log("not-base64!!")


async def test_fight_to_the_end_folds_close_events() -> None:
    """A script that kills the foe ends the combat and folds in the close events.

    Also pins the trailing-command rule: commands after the fight is over are
    simply not applied, and that is not a rejection.
    """
    long_script: list[Command] = []
    for _ in range(12):
        long_script.append(hero_attack())
        long_script.append(MonsterTurnCommand())
    out = await replay_fight(make_log(long_script), *fresh_specs())
    assert out.is_over
    assert out.rejected_reason is None
    assert out.accepted < len(long_script)  # trailing commands unreachable
    assert out.outcome is not None
    assert out.all_events[-1].type == "combat_ended"
    assert "mon:gob" in out.view.dead_ids
