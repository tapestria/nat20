"""C24 — grid movement & reactions.

Transcribed from the local C24 scenario catalog (S01–S15).
Every setup is a 10x10 ``GridScene`` at ``rng_seed=1`` unless the scenario
names another seed or grid; positions are ``cell(col, row)``. SRD 5.2
Opportunity Attacks: "You can make an Opportunity Attack when a creature that
you can see leaves your reach using its action, its Bonus Action, its
Reaction, or one of its speeds. ... The attack occurs right before the
creature leaves your reach." Monster flee is DM-adjudicated AI, not SRD text.
"""

from __future__ import annotations

from typing import Any

from dnd5e_engine import ActiveEffect, PlayerIntent
from dnd5e_engine.events import (
    ActorMoved,
    AttackRolled,
    CombatantMoved,
    DamageApplied,
    IntentSubmitted,
    ReactionTriggered,
)
from dnd5e_engine.orchestrator import (
    _get_live,
    advance_monster_turn,
    start_combat,
    submit_player_intent,
)
from dnd5e_engine.spatial import GridTopology
from dnd5e_engine.specs import EncounterMemberSpec, GridScene, PartyMemberSpec
from tests.e2e.harness import (
    adjacent_cells,
    cell,
    events_of,
    grid_scene,
    run_async,
)


def _hero(**fields: Any) -> PartyMemberSpec:
    """A PC on 0,0 who acts first: 30 HP, AC 12, no equipment."""
    base: dict[str, Any] = {
        "entity_id": "char:hero",
        "name": "Hero",
        "initiative": 20,
        "hp_current": 30,
        "hp_max": 30,
        "ac": 12,
        "zone_id": cell(0, 0),
    }
    return PartyMemberSpec(**(base | fields))


def _goblin(entity_id: str = "mon:goblin", **fields: Any) -> EncounterMemberSpec:
    """A Goblin Warrior (real corpus slug) on 1,0 that acts last: 20 HP, AC 15."""
    base: dict[str, Any] = {
        "entity_id": entity_id,
        "entity_type": "Monster",
        "name": entity_id.removeprefix("mon:").title(),
        "initiative": 1,
        "hp_current": 20,
        "hp_max": 20,
        "ac": 15,
        "monster_template_slug": "goblin-warrior",
        "zone_id": cell(1, 0),
    }
    return EncounterMemberSpec(**(base | fields))


def _start(
    party: list[PartyMemberSpec],
    encounter: list[EncounterMemberSpec],
    *,
    session: str,
    seed: int = 1,
    grid: GridScene | None = None,
    **kwargs: Any,
):
    async def _inner():
        start = await start_combat(
            session_id=session,
            party=party,
            encounter=encounter,
            grid_scene=grid or grid_scene(),
            rng_seed=seed,
            **kwargs,
        )
        return start.handle, _get_live(start.handle)

    return run_async(_inner())


def _act(handle, actor_id: str, **intent: Any) -> None:
    run_async(submit_player_intent(handle, actor_id=actor_id, intent=PlayerIntent(**intent)))


def _monster_turn(handle) -> None:
    run_async(advance_monster_turn(handle))


def _aoos(live) -> list[AttackRolled]:
    return [e for e in events_of(live, AttackRolled) if e.is_opportunity_attack]


def _moves(live, actor_id: str) -> list[tuple[str, str, int]]:
    return [
        (e.from_zone, e.to_zone, e.distance_ft)
        for e in events_of(live, ActorMoved)
        if e.actor_id == actor_id
    ]


def _combatant(live, entity_id: str):
    return next(c for c in live.initiative if c.entity_id == entity_id)


def _status(entity_id: str, status: str) -> ActiveEffect:
    return ActiveEffect(
        id=f"effect:{status}",
        name=status.title(),
        origin="test:c24",
        target_id=entity_id,
        statuses={status},
    )


def test_adjacent_cells_is_a_block_of_mutually_adjacent_cells() -> None:
    grid = GridTopology(GridScene(width=10, height=10))
    block = adjacent_cells(4, at=(3, 5))
    assert block == [cell(3, 5), cell(3, 6), cell(4, 5), cell(4, 6)]
    assert all(grid.distance_ft(a, b) == 5 for a in block for b in block if a != b)
    assert adjacent_cells(2) == [cell(0, 0), cell(0, 1)]


def test_c24_s01_leaving_reach_mid_move_draws_one_opportunity_attack() -> None:
    handle, live = _start([_hero()], [_goblin()], session="e2e-c24-s01")
    _act(handle, "char:hero", intent_type="move", target_zone_id=cell(0, 3))

    [aoo] = _aoos(live)
    assert (aoo.attacker_id, aoo.target_id, aoo.natural) == ("mon:goblin", "char:hero", 5)
    # D24.1: the move splits at the provoking step, the attack between.
    assert _moves(live, "char:hero") == [
        (cell(0, 0), cell(0, 1), 5),
        (cell(0, 1), cell(0, 3), 10),
    ]
    first, second = (e for e in events_of(live, ActorMoved) if e.actor_id == "char:hero")
    assert live.event_log.index(first) < live.event_log.index(aoo) < live.event_log.index(second)
    assert _combatant(live, "mon:goblin").reaction_available is False
    assert _combatant(live, "char:hero").movement_remaining == 15
    assert live.actor_zone["char:hero"] == cell(0, 3)


def test_c24_s02_moving_around_inside_reach_never_provokes() -> None:
    handle, live = _start([_hero()], [_goblin(zone_id=cell(1, 1))], session="e2e-c24-s02")
    _act(handle, "char:hero", intent_type="move", target_zone_id=cell(2, 0))
    assert _aoos(live) == []
    assert _moves(live, "char:hero") == [(cell(0, 0), cell(2, 0), 10)]

    _act(handle, "char:hero", intent_type="move", target_zone_id=cell(3, 0))
    assert [(e.attacker_id, e.target_id) for e in _aoos(live)] == [("mon:goblin", "char:hero")]
    assert _moves(live, "char:hero")[-1] == (cell(2, 0), cell(3, 0), 5)


def test_c24_s03_disengage_suppresses_opportunity_attacks_from_either_side() -> None:
    # Control: the same walk without Disengage provokes.
    handle, live = _start([_hero()], [_goblin()], session="e2e-c24-s03-control")
    _act(handle, "char:hero", intent_type="move", target_zone_id=cell(0, 2))
    assert [e.attacker_id for e in _aoos(live)] == ["mon:goblin"]

    # A character's Disengage.
    handle, live = _start([_hero()], [_goblin()], session="e2e-c24-s03-pc")
    _act(handle, "char:hero", intent_type="disengage")
    _act(handle, "char:hero", intent_type="move", target_zone_id=cell(0, 2))
    assert _aoos(live) == []
    assert _combatant(live, "mon:goblin").reaction_available is True
    assert live.actor_zone["char:hero"] == cell(0, 2)

    # A host-driven foe's Disengage: the goblin acts first and walks off.
    handle, live = _start(
        [_hero(initiative=1)], [_goblin(initiative=20)], session="e2e-c24-s03-foe"
    )
    _act(handle, "mon:goblin", intent_type="disengage")
    _act(handle, "mon:goblin", intent_type="move", target_zone_id=cell(3, 0))
    assert _aoos(live) == []
    assert _combatant(live, "char:hero").reaction_available is True
    assert live.actor_zone["mon:goblin"] == cell(3, 0)


def test_c24_s04_a_host_driven_foe_draws_the_heros_attack_not_its_allys() -> None:
    handle, live = _start(
        [_hero(initiative=1)],
        [_goblin(initiative=20), _goblin("mon:ally", zone_id=cell(1, 1), initiative=10)],
        session="e2e-c24-s04",
    )
    _act(handle, "mon:goblin", intent_type="move", target_zone_id=cell(4, 0))

    assert [(e.attacker_id, e.target_id) for e in _aoos(live)] == [("char:hero", "mon:goblin")]
    assert _combatant(live, "char:hero").reaction_available is False
    assert _combatant(live, "mon:ally").reaction_available is True
    assert _moves(live, "mon:goblin") == [(cell(1, 0), cell(4, 0), 15)]


def test_c24_s05_an_ai_closing_walk_draws_the_attack_of_the_pc_it_leaves() -> None:
    handle, live = _start(
        [
            _hero(entity_id="char:near", name="Near", initiative=10),
            _hero(
                entity_id="char:far", name="Far", zone_id=cell(5, 0), hp_current=10, initiative=5
            ),
        ],
        [_goblin(initiative=20)],
        session="e2e-c24-s05",
    )
    _monster_turn(handle)  # the goblin closes on Far, the lowest-HP enemy

    [aoo] = _aoos(live)
    assert (aoo.attacker_id, aoo.target_id) == ("char:near", "mon:goblin")
    assert _moves(live, "mon:goblin") == [
        (cell(1, 0), cell(2, 0), 5),
        (cell(2, 0), cell(3, 0), 5),
        (cell(3, 0), cell(4, 0), 5),
    ]
    first_step = next(e for e in events_of(live, ActorMoved) if e.actor_id == "mon:goblin")
    assert live.event_log.index(aoo) < live.event_log.index(first_step)


def test_c24_s06_a_ten_foot_reach_threatens_ten_feet() -> None:
    # 10 ft -> 15 ft leaves a 10-ft reach.
    handle, live = _start(
        [_hero(initiative=1, reach_ft=10)],
        [_goblin(initiative=20, zone_id=cell(2, 0))],
        session="e2e-c24-s06-leaves",
    )
    _act(handle, "mon:goblin", intent_type="move", target_zone_id=cell(3, 0))
    assert [(e.attacker_id, e.target_id) for e in _aoos(live)] == [("char:hero", "mon:goblin")]

    # 5 ft -> 10 ft stays inside it.
    handle, live = _start(
        [_hero(initiative=1, reach_ft=10)], [_goblin(initiative=20)], session="e2e-c24-s06-stays"
    )
    _act(handle, "mon:goblin", intent_type="move", target_zone_id=cell(2, 0))
    assert _aoos(live) == []
    assert _combatant(live, "char:hero").reaction_available is True


def test_c24_s07_forced_movement_provokes_nothing() -> None:
    handle, live = _start(
        [_hero(entity_id="char:brute", name="Brute", strength=18, character_level=5)],
        [
            EncounterMemberSpec(
                entity_id="mon:target",
                entity_type="Monster",
                name="Target",
                initiative=1,
                hp_current=20,
                hp_max=20,
                ac=10,
                zone_id=cell(1, 0),
            )
        ],
        session="e2e-c24-s07",
    )
    # SRD 5.2 Shove, pushing: the Target fails its save (a natural 5 against
    # DC 15) and is pushed 5 ft straight away — forced, not its movement.
    _act(
        handle,
        "char:brute",
        intent_type="shove",
        weapon_id="unarmed-strike",
        target_id="mon:target",
        shove_push=True,
    )
    pushed = [e for e in events_of(live, CombatantMoved) if e.actor_id == "mon:target"]
    assert [(e.from_zone, e.to_zone, e.forced) for e in pushed] == [(cell(1, 0), cell(2, 0), True)]
    assert _aoos(live) == []
    assert _combatant(live, "char:brute").reaction_available is True

    # The Reaction the push left unspent answers the Target's own walk out.
    _act(handle, "mon:target", intent_type="move", target_zone_id=cell(1, 1))
    _act(handle, "mon:target", intent_type="move", target_zone_id=cell(1, 2))
    assert [(e.attacker_id, e.target_id) for e in _aoos(live)] == [("char:brute", "mon:target")]


def test_c24_s08_a_blinded_reactor_or_an_invisible_mover_draws_nothing() -> None:
    def walk_away(session: str, effects: list[ActiveEffect]):
        handle, live = _start([_hero()], [_goblin()], session=session, active_effects=effects)
        _act(handle, "char:hero", intent_type="move", target_zone_id=cell(0, 2))
        return live

    control = walk_away("e2e-c24-s08-control", [])
    assert [e.attacker_id for e in _aoos(control)] == ["mon:goblin"]
    for target_id, status in (("mon:goblin", "blinded"), ("char:hero", "invisible")):
        live = walk_away(f"e2e-c24-s08-{status}", [_status(target_id, status)])
        assert _aoos(live) == [], status
        assert _combatant(live, "mon:goblin").reaction_available is True, status
        assert live.actor_zone["char:hero"] == cell(0, 2), status


def test_c24_s09_a_pc_dropped_to_0_hp_stops_where_it_stood() -> None:
    handle, live = _start([_hero(hp_current=1)], [_goblin(attack_bonus=20)], session="e2e-c24-s09")
    _act(handle, "char:hero", intent_type="move", target_zone_id=cell(0, 3))

    [aoo] = _aoos(live)
    assert aoo.is_hit is True  # a natural 5 + 20
    hero = _combatant(live, "char:hero")
    assert hero.hp_current == 0
    # It stops on 0,1, the cell it was leaving: only the run before the attack.
    assert live.actor_zone["char:hero"] == cell(0, 1)
    assert _moves(live, "char:hero") == [(cell(0, 0), cell(0, 1), 5)]


def test_c24_s10_a_fleeing_monster_runs_30_feet_and_records_pass() -> None:
    handle, live = _start(
        [_hero(initiative=1)],
        [_goblin(zone_id=cell(3, 0), hp_current=1, initiative=20)],
        session="e2e-c24-s10",
    )
    _monster_turn(handle)

    assert _moves(live, "mon:goblin") == [(cell(c, 0), cell(c + 1, 0), 5) for c in range(3, 9)]
    assert live.actor_zone["mon:goblin"] == cell(9, 0)
    assert [
        e.intent_type for e in events_of(live, IntentSubmitted) if e.actor_id == "mon:goblin"
    ] == ["pass"]
    assert events_of(live, AttackRolled) == []
    assert _combatant(live, "mon:goblin").has_fled is True


def test_c24_s11_a_monster_fleeing_from_beside_the_hero_draws_its_attack() -> None:
    handle, live = _start(
        [_hero(initiative=1)], [_goblin(hp_current=1, initiative=20)], session="e2e-c24-s11"
    )
    _monster_turn(handle)

    [aoo] = _aoos(live)
    assert (aoo.attacker_id, aoo.target_id, aoo.is_hit) == ("char:hero", "mon:goblin", False)
    first_step = next(e for e in events_of(live, ActorMoved) if e.actor_id == "mon:goblin")
    assert live.event_log.index(aoo) < live.event_log.index(first_step)
    assert live.actor_zone["mon:goblin"] == cell(7, 0)
    assert _combatant(live, "mon:goblin").has_fled is True


def test_c24_s12_a_fleeing_monster_never_ends_on_a_creature_or_walks_through_an_enemy() -> None:
    # An ally holds the farthest cell: the goblin ends beside it, not on it.
    handle, live = _start(
        [_hero(initiative=1)],
        [
            _goblin(zone_id=cell(3, 0), hp_current=1, initiative=20),
            _goblin("mon:ally", zone_id=cell(9, 0), initiative=5),
        ],
        session="e2e-c24-s12-ally",
    )
    _monster_turn(handle)
    assert live.actor_zone["mon:goblin"] == cell(9, 1)

    # A one-row corridor: only through the second hero could it get farther.
    handle, live = _start(
        [
            _hero(initiative=1),
            _hero(entity_id="char:wall", name="Wall", zone_id=cell(5, 0), initiative=2),
        ],
        [_goblin(zone_id=cell(2, 0), hp_current=1, initiative=20)],
        session="e2e-c24-s12-corridor",
        grid=grid_scene(height=1),
    )
    _monster_turn(handle)
    assert _moves(live, "mon:goblin") == []
    assert _combatant(live, "mon:goblin").has_fled is True

    # Cornered by blocked cells with the hero beside it: it holds.
    handle, live = _start(
        [_hero(zone_id=cell(1, 1), initiative=1)],
        [_goblin(zone_id=cell(0, 0), hp_current=1, initiative=20)],
        session="e2e-c24-s12-corner",
        grid=grid_scene(blocked_cells=[cell(2, 0), cell(2, 1), cell(2, 2), cell(0, 2), cell(1, 2)]),
    )
    _monster_turn(handle)
    assert _moves(live, "mon:goblin") == []


def test_c24_s13_a_stunned_monster_below_its_flee_threshold_takes_no_flee_stance() -> None:
    handle, live = _start(
        [_hero(initiative=1)],
        [_goblin(zone_id=cell(3, 0), hp_current=1, initiative=20)],
        session="e2e-c24-s13",
        active_effects=[_status("mon:goblin", "stunned")],
    )
    _monster_turn(handle)

    assert _moves(live, "mon:goblin") == []
    assert _combatant(live, "mon:goblin").has_fled is False
    assert [
        e.intent_type for e in events_of(live, IntentSubmitted) if e.actor_id == "mon:goblin"
    ] == ["pass"]


def test_c24_s14_a_great_weapon_fighting_greatsword_attack_through_half_cover() -> None:
    def run(seed: int):
        handle, live = _start(
            [
                _hero(
                    entity_id="char:fighter",
                    name="Fighter",
                    initiative=1,
                    strength=16,
                    equipment=("greatsword",),
                    fighting_style="great-weapon-fighting",
                )
            ],
            [_goblin(initiative=20, hp_current=40, hp_max=40)],
            session=f"e2e-c24-s14-{seed}",
            seed=seed,
            grid=grid_scene(cover_cells={cell(1, 0): "half"}),
        )
        _act(handle, "mon:goblin", intent_type="move", target_zone_id=cell(2, 0))
        [aoo] = _aoos(live)
        return live, aoo

    # Seed 7: a natural 11 + 5 (STR +3, PB +2) = 16 beats AC 15 but not the
    # 17 half cover makes it.
    _live, aoo = run(7)
    assert (aoo.attacker_id, aoo.natural, aoo.modifier, aoo.roll_total) == (
        "char:fighter",
        11,
        5,
        16,
    )
    assert aoo.is_hit is False

    # Seed 9: a natural 15 + 5 = 20 hits; Great Weapon Fighting treats each
    # 1 or 2 of the greatsword's 2d6 as a 3.
    live, aoo = run(9)
    assert aoo.is_hit is True
    [damage] = [e for e in events_of(live, DamageApplied) if e.target_id == "mon:goblin"]
    assert (damage.source_id, damage.damage_type) == ("greatsword", "slashing")
    assert damage.amount >= 2 * 3 + 3


def test_c24_s15_a_goblins_scimitar_meets_the_movers_readied_shield() -> None:
    def run(seed: int):
        handle, live = _start(
            [
                _hero(
                    entity_id="char:wiz",
                    name="Wizard",
                    class_slug="wizard",
                    intelligence=16,
                    spells_known=["shield"],
                    spell_slots={1: 2},
                )
            ],
            [_goblin(attack_bonus=4)],
            session=f"e2e-c24-s15-{seed}",
            seed=seed,
        )
        _act(
            handle,
            "char:wiz",
            intent_type="ready",
            spell_id="shield",
            reaction_trigger="hit_by_attack",
        )
        _act(handle, "mon:goblin", intent_type="pass")
        _act(handle, "char:wiz", intent_type="move", target_zone_id=cell(0, 2))
        [aoo] = _aoos(live)
        return live, aoo

    # Seed 9: Shield fires before the swing; a natural 15 + 4 = 19 still
    # beats AC 12 + 5, and the Scimitar deals Slashing damage.
    live, aoo = run(9)
    [shield] = [e for e in events_of(live, ReactionTriggered) if e.actor_id == "char:wiz"]
    assert live.event_log.index(shield) < live.event_log.index(aoo)
    assert (aoo.attacker_id, aoo.natural, aoo.roll_total, aoo.is_hit) == (
        "mon:goblin",
        15,
        19,
        True,
    )
    [damage] = [e for e in events_of(live, DamageApplied) if e.target_id == "char:wiz"]
    assert damage.damage_type == "slashing"

    # Seed 7: a natural 11 + 4 = 15 would hit AC 12; Shield's +5 turns it away.
    _live, aoo = run(7)
    assert (aoo.natural, aoo.roll_total, aoo.is_hit) == (11, 15, False)
