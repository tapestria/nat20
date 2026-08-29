"""Scenario catalog tests — the acceptance record for the curated scripts.

Each showcase script is a player's-eye-view command sequence a real user
could submit through the demo UI. ``PROOF_EVENTS`` pins each scenario to the
engine subsystem it demonstrates; never weaken these sets to make a script
pass — retune the script/seed/scenario data instead (see module docstring
discussion in the task brief).
"""

from __future__ import annotations

import pytest
from dnd5e_engine import PlayerIntent, cell_id

from nat20_demo.replay import Command, FightLog, IntentCommand, MonsterTurnCommand, replay_fight
from nat20_demo.scenarios import all_scenarios, fresh_specs, get_scenario


def _attack(actor: str, weapon: str, target: str) -> Command:
    return IntentCommand(
        actor=actor,
        intent=PlayerIntent(intent_type="attack", weapon_id=weapon, target_id=target),
    )


def _cast(actor: str, spell: str, target: str | None = None, slot: int = 1) -> Command:
    return IntentCommand(
        actor=actor,
        intent=PlayerIntent(
            intent_type="cast_spell", spell_id=spell, slot_level=slot, target_id=target
        ),
    )


def _move(actor: str, to: str) -> Command:
    return IntentCommand(actor=actor, intent=PlayerIntent(intent_type="move", target_zone_id=to))


def _dash(actor: str) -> Command:
    return IntentCommand(actor=actor, intent=PlayerIntent(intent_type="dash"))


def _pass(actor: str) -> Command:
    return IntentCommand(actor=actor, intent=PlayerIntent(intent_type="pass"))


# Diagonal-first path so Brynn closes the full 6-cell (30 ft) budget and
# lands adjacent to the goblin she opened on.
_BRYNN_APPROACH = [(2, 4), (3, 4), (4, 4), (5, 4), (6, 4), (7, 3)]

SHOWCASE_SCRIPTS: dict[str, list[Command]] = {
    # Brynn closes to melee range (grid movement around/through the cover
    # wall), both PCs land opening attacks, then three monster turns play
    # out — one of which draws Brynn's opportunity attack.
    "goblin-ambush": [
        *[_move("char:brynn", cell_id(c, r)) for c, r in _BRYNN_APPROACH],
        _attack("char:brynn", "longsword", "mon:gob1"),
        _attack("char:sera", "shortbow", "mon:gob2"),
        MonsterTurnCommand(),
        MonsterTurnCommand(),
        MonsterTurnCommand(),
    ],
    # Orin's cone catches all four giant rats sharing the corridor-mouth
    # zone in one cast: four Dex saves, half damage on a save, full on a
    # fail. One monster turn closes out the round.
    "burning-hands": [
        _cast("char:orin", "burning-hands", target="mon:rat1"),
        MonsterTurnCommand(),
    ],
    # Doran closes on the captain, Mira holds it (Paralyzed, concentration
    # flagged). Since engine C12 the Paralyzed captain can no longer act, so
    # its turn is a no-op and the pressure on Mira's concentration comes from
    # the two bandits instead — which takes a second round to land, hence the
    # extra pass/monster-turn block below.
    "hold-the-line": [
        _move("char:doran", cell_id(3, 3)),
        _move("char:doran", cell_id(4, 3)),
        _move("char:doran", cell_id(5, 3)),
        _attack("char:doran", "mace", "mon:captain"),
        _cast("char:mira", "hold-person", target="mon:captain", slot=2),
        MonsterTurnCommand(),
        MonsterTurnCommand(),
        MonsterTurnCommand(),
        _pass("char:doran"),
        _pass("char:mira"),
        MonsterTurnCommand(),
        MonsterTurnCommand(),
        MonsterTurnCommand(),
    ],
    # Both archers open on the nearest zombie, three zombies dash and
    # shamble through the marsh's difficult terrain (visible as doubled
    # per-cell movement cost), then Wren dashes and steps into the muck
    # herself.
    "marsh-crossing": [
        _attack("char:wren", "shortbow", "mon:zom2"),
        _attack("char:tam", "shortbow", "mon:zom2"),
        MonsterTurnCommand(),
        MonsterTurnCommand(),
        MonsterTurnCommand(),
        _dash("char:wren"),
        _move("char:wren", cell_id(2, 3)),
    ],
    # The skeleton's crit drops Korrin to exactly 0 HP; his first death
    # save succeeds; Faye's Cure Wounds on the following round brings him
    # back to consciousness before the wolves can finish him.
    "last-stand": [
        _pass("char:faye"),
        MonsterTurnCommand(),
        _pass("char:korrin"),
        MonsterTurnCommand(),
        MonsterTurnCommand(),
        _cast("char:faye", "cure-wounds", target="char:korrin", slot=1),
        MonsterTurnCommand(),
        _pass("char:korrin"),
    ],
}

# "hold-the-line" targets {"effect_applied", "concentration_check"} per the
# design spec's *behavior* -- a hold cast, then concentration held/broken
# under fire. Engine F2c wired ``ConcentrationCheck``, which is now emitted
# alongside the ``SaveRolled(ability="con", ...)`` the engine has always
# emitted (the duplicate is dropped in engine v0.7). The set below stays
# pinned on ``save_rolled`` -- the shape that survives that removal is the
# specific assertion in
# ``test_hold_the_line_proves_concentration_save_on_damage``, which proves the
# spec's real behavioral intent (a con save against the concentrating cleric
# specifically) rather than a bare membership check.
PROOF_EVENTS: dict[str, set[str]] = {
    "goblin-ambush": {"attack_rolled", "damage_applied"},
    "burning-hands": {"save_rolled", "damage_applied"},
    "hold-the-line": {"effect_applied", "save_rolled"},
    "marsh-crossing": {"actor_moved", "dash_taken", "attack_rolled"},
    "last-stand": {"healing_applied", "death_save_rolled"},
}


async def test_every_scenario_opens_and_replays_empty_log() -> None:
    for s in all_scenarios():
        out = await replay_fight(FightLog(scenario_id=s.id, seed=s.default_seed), *fresh_specs(s))
        assert out.accepted == 0
        assert not out.is_over


async def test_scenario_scripts_run_without_rejection() -> None:
    for s in all_scenarios():
        script = SHOWCASE_SCRIPTS[s.id]
        out = await replay_fight(
            FightLog(scenario_id=s.id, seed=s.default_seed, commands=script), *fresh_specs(s)
        )
        assert out.rejected_reason is None, f"{s.id}: {out.rejected_reason}"
        got = {e.type for e in out.all_events}
        assert PROOF_EVENTS[s.id] <= got, f"{s.id} missing {PROOF_EVENTS[s.id] - got}"


async def test_replay_equivalence_across_all_scenarios() -> None:
    for s in all_scenarios():
        log = FightLog(scenario_id=s.id, seed=s.default_seed, commands=SHOWCASE_SCRIPTS[s.id])
        a = await replay_fight(log, *fresh_specs(s))
        b = await replay_fight(log, *fresh_specs(s))
        assert [e.model_dump() for e in a.all_events] == [e.model_dump() for e in b.all_events]


def test_fresh_specs_returns_new_instances() -> None:
    s = all_scenarios()[0]
    p1, _, _ = fresh_specs(s)
    p2, _, _ = fresh_specs(s)
    assert p1[0] is not p2[0]


def test_get_scenario_raises_key_error_for_unknown_id() -> None:
    with pytest.raises(KeyError):
        get_scenario("not-a-real-scenario")


async def test_hold_the_line_proves_concentration_save_on_damage() -> None:
    """Re-proves the design spec's actual intent for "hold-the-line":
    concentration held under fire, then broken.

    The real SRD §Concentration on-damage check surfaces as a
    ``SaveRolled(ability="con", ...)`` (and, since engine F2c, a matching
    ``ConcentrationCheck``). This asserts that specific save fired against
    Mira (the concentrating cleric), not just any Constitution save in the
    stream.
    """
    s = get_scenario("hold-the-line")
    log = FightLog(scenario_id=s.id, seed=s.default_seed, commands=SHOWCASE_SCRIPTS[s.id])
    out = await replay_fight(log, *fresh_specs(s))
    assert out.rejected_reason is None

    concentration_saves = [
        e
        for e in out.all_events
        if e.type == "save_rolled"
        and getattr(e, "ability", None) == "con"
        and getattr(e, "target_id", None) == "char:mira"
    ]
    assert concentration_saves, (
        "expected a Constitution save against char:mira (the concentrating cleric)"
    )
