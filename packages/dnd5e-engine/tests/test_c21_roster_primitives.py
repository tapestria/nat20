"""C21 — the roster primitives. SRD 5.2 Summon Dragon: "In combat, the
creature shares your Initiative count, but it takes its turn immediately after
yours"; "The creature disappears when it drops to 0 Hit Points or when the
spell ends." A creature can join the initiative order at any slot and leave
it from any slot mid-combat: the creature whose turn it is keeps it, nobody is
skipped, a departed creature leaves no per-entity state behind, and nothing
draws a die."""

from __future__ import annotations

from dnd5e_engine import ActiveEffect, CombatHandle, PlayerIntent
from dnd5e_engine.events import (
    CombatantLeft,
    RechargeRolled,
    RoundStarted,
    TurnEnded,
    TurnPhase,
    TurnStarted,
)
from dnd5e_engine.orchestrator import (
    _Construct,
    _current_actor,
    _end_action,
    _end_turn_and_advance,
    _insert_into_roster,
    _leave_roster,
    _LiveCombat,
    _PendingReaction,
    _remove_from_roster,
    _run_monster_turn_start,
    _Transform,
)
from dnd5e_engine.spatial import cell_id
from dnd5e_engine.types.combat import Combatant
from tests.c21_support import act, events, foe, monster_turn, pc, roster, start

HERO = "char:hero"
NEW = "mon:newcomer"
NEW_ZONE = cell_id(9, 9)
# The per-entity maps and sets ``_purge_entity_state`` covers (R4). An
# owner-keyed counter is not a creature's own state, so it is not listed.
PURGED = (
    "actor_zone",
    "monster_slug_by_entity",
    "xp_value_by_entity",
    "tracked_hp",
    "tracked_temp_hp",
    "undead_fortitude_holds",
    "active_conditions",
    "active_effects",
    "expended_resources",
    "spell_slots_by_entity",
    "pact_slots_by_entity",
    "spells_known_by_entity",
    "custom_counters_by_entity",
    "concentration_chain",
    "concentration_rounds_remaining",
    "reaction_effects_pending_expiry",
    "help_grants",
    "vex_grants",
    "sap_marks",
    "slow_marks",
    "monster_action_uses_by_entity",
    "legendary_resistance_armed",
    "transforms",
    "hidden_entities",
    "rage_bonus_extensions",
)


def _combat(seed: int = 1) -> tuple[CombatHandle, _LiveCombat]:
    """The hero (20) and three template-less foes (15, 10, 5), none adjacent."""
    return start(
        [pc()],
        seed=seed,
        encounter=[
            foe(entity_id="mon:a", name="A", initiative=15, zone_id=cell_id(5, 0)),
            foe(entity_id="mon:b", name="B", initiative=10, zone_id=cell_id(6, 0)),
            foe(entity_id="mon:c", name="C", initiative=5, zone_id=cell_id(7, 0)),
        ],
    )


def _newcomer() -> Combatant:
    return Combatant(
        entity_id=NEW,
        entity_type="Monster",
        name="Newcomer",
        initiative=12,
        hp_current=30,
        hp_max=30,
    )


def _seated(index: int, seed: int = 1) -> tuple[CombatHandle, _LiveCombat]:
    """``_combat`` with the newcomer inserted at ``index`` before any turn ends."""
    handle, live = _combat(seed)
    _insert_into_roster(live, _newcomer(), index, zone_id=NEW_ZONE)
    return handle, live


def test_insert_at_every_index_keeps_the_current_actor() -> None:
    for current in range(4):
        for index in range(5):
            _, live = _combat()
            live.current_turn_index = current
            order = roster(live)
            actor = _current_actor(live).entity_id
            logged = len(live.event_log)
            _insert_into_roster(live, _newcomer(), index, zone_id=NEW_ZONE)
            case = f"insert at {index} while {current} is current"
            assert _current_actor(live).entity_id == actor, case
            assert roster(live) == [*order[:index], NEW, *order[index:]], case
            assert live.actor_zone[NEW] == NEW_ZONE, case
            assert live.tracked_hp[NEW] == 30, case
            assert len(live.event_log) == logged, case


def test_remove_at_every_index_keeps_the_turn_order() -> None:
    for current in range(5):
        for index in range(5):
            if index == current:
                continue
            _, live = _seated(2)
            live.current_turn_index = current
            order = roster(live)
            removed = order[index]
            case = f"remove {index} while {current} is current"
            assert _remove_from_roster(live, removed) is False, case
            assert _current_actor(live).entity_id == order[current], case
            assert roster(live) == [e for e in order if e != removed], case


def test_removing_the_current_actor_opens_the_next_turn() -> None:
    handle, live = _seated(2)  # hero, A, the newcomer, B, C
    act(handle, HERO, intent_type="pass")
    monster_turn(handle)  # A
    assert _current_actor(live).entity_id == NEW
    ended_before = live.last_ended_turn
    logged = len(live.event_log)
    _leave_roster(live, NEW, "zero_hp")
    tail = live.event_log[logged:]
    assert tail[0] == CombatantLeft(entity_id=NEW, reason="zero_hp")
    assert tail[1] == TurnStarted(actor_id="mon:b")
    assert tail[2] == TurnPhase(actor_id="mon:b", phase="turn_start", round_number=1)
    assert not [e for e in events(live, TurnEnded) if e.actor_id == NEW]
    assert not [e for e in events(live, TurnPhase) if e.actor_id == NEW and e.phase == "turn_end"]
    assert live.last_ended_turn == ended_before == (1, "mon:a")
    assert roster(live) == [HERO, "mon:a", "mon:b", "mon:c"]
    assert (live.current_turn_index, live.round_number) == (2, 1)


def test_removing_the_last_slot_while_current_wraps_to_a_new_round() -> None:
    handle, live = _seated(4)  # hero, A, B, C, the newcomer
    act(handle, HERO, intent_type="pass")
    for _ in range(3):
        monster_turn(handle)  # A, B, C
    assert _current_actor(live).entity_id == NEW
    logged = len(live.event_log)
    _leave_roster(live, NEW, "spell_ended")
    tail = live.event_log[logged:]
    assert tail[0] == CombatantLeft(entity_id=NEW, reason="spell_ended")
    assert tail[1] == RoundStarted(round_number=2)
    assert tail[2] == TurnPhase(actor_id=None, phase="round_start", round_number=2)
    assert tail[3] == TurnStarted(actor_id=HERO)
    assert (live.current_turn_index, live.round_number) == (0, 2)


def test_ending_a_departed_actors_turn_is_a_no_op() -> None:
    handle, live = _seated(2)
    act(handle, HERO, intent_type="pass")
    monster_turn(handle)  # A
    _leave_roster(live, NEW, "zero_hp")
    logged = len(live.event_log)
    _end_turn_and_advance(live, NEW)
    _end_action(live, NEW, PlayerIntent(intent_type="attack", target_id=HERO))
    assert len(live.event_log) == logged
    assert _current_actor(live).entity_id == "mon:b"


def test_leaving_twice_is_a_no_op() -> None:
    _, live = _seated(2)
    _leave_roster(live, NEW, "concentration_drop")
    logged = len(live.event_log)
    _leave_roster(live, NEW, "concentration_drop")
    assert len(live.event_log) == logged
    assert events(live, CombatantLeft) == [
        CombatantLeft(entity_id=NEW, reason="concentration_drop")
    ]
    assert roster(live) == [HERO, "mon:a", "mon:b", "mon:c"]


def test_a_departed_creature_leaves_no_per_entity_state() -> None:
    _, live = _seated(2)
    bless_on_new = (NEW, "effect:bless", f"cast:bless:{HERO}")
    held_other = ("mon:a", "effect:hold", f"cast:hold:{HERO}")
    live.tracked_temp_hp[NEW] = 5
    live.monster_slug_by_entity[NEW] = "draconic-spirit"
    live.xp_value_by_entity[NEW] = 10
    live.undead_fortitude_holds[NEW] = True
    live.active_conditions[NEW] = {"prone"}
    live.active_effects[NEW] = [
        ActiveEffect(id="effect:bless", name="Bless", origin=bless_on_new[2], target_id=NEW)
    ]
    live.expended_resources[NEW] = {"slot": 1}
    live.spell_slots_by_entity[NEW] = {1: 1}
    live.pact_slots_by_entity[NEW] = {1: 1}
    live.spells_known_by_entity[NEW] = ["bless"]
    live.custom_counters_by_entity[NEW] = {"feature": {"uses": 1}}
    live.concentration_chain[NEW] = [("mon:a", "effect:x", f"cast:x:{NEW}")]
    live.concentration_chain[HERO] = [bless_on_new]  # another caster's, on it: kept
    live.concentration_rounds_remaining[NEW] = 10
    live.conditions_by_effect[bless_on_new] = ["prone"]
    live.conditions_by_effect[held_other] = ["paralyzed"]
    live.repeat_save_on_turn_end[(NEW, "effect:hold", f"cast:hold:{HERO}")] = [{"ability": "wis"}]
    live.repeat_save_on_turn_end[held_other] = [{"ability": "wis"}]
    live.pending_reactions.append(
        _PendingReaction(owner_id=NEW, trigger="cast_spell", spell_id=None, slot_level=None)
    )
    live.pending_reactions.append(
        _PendingReaction(owner_id=HERO, trigger="cast_spell", spell_id=None, slot_level=None)
    )
    live.reaction_effects_pending_expiry[NEW] = [(NEW, "effect:shield", f"cast:shield:{NEW}")]
    live.help_grants[NEW] = [HERO]  # helped against it
    live.help_grants["mon:a"] = [NEW, HERO]  # it helped
    live.help_grants["mon:b"] = [NEW]  # it helped, alone: the entry goes
    live.hidden_entities.add(NEW)
    live.vex_grants[NEW] = {"mon:a": 2}
    live.vex_grants[HERO] = {NEW: 2, "mon:a": 1}
    live.vex_grants["mon:b"] = {NEW: 2}
    live.rage_bonus_extensions.add(NEW)
    live.sap_marks[NEW] = HERO
    live.sap_marks["mon:a"] = NEW
    live.sap_marks["mon:b"] = HERO
    live.slow_marks[NEW] = {HERO}
    live.slow_marks["mon:a"] = {NEW, HERO}
    live.slow_marks["mon:b"] = {NEW}
    live.monster_action_uses_by_entity[NEW] = {}
    live.legendary_resistance_armed[NEW] = 1
    live.transforms[NEW] = _Transform(
        entity_id=NEW,
        form_slug="wolf",
        source="polymorph",
        effect_id="effect:polymorph",
        origin=f"cast:polymorph:{HERO}",
        stash={},
        original_monster_slug=None,
        original_action_uses=None,
        form_proficiency_bonus=2,
        attacks_per_action=1,
        clears_temp_hp_on_end=True,
    )
    for owner in (NEW, HERO):
        construct_id = f"construct:{owner}:spiritual-weapon"
        live.constructs[construct_id] = _Construct(
            construct_id=construct_id,
            owner_id=owner,
            spell_id="spiritual-weapon",
            cell=cell_id(8, 8),
            slot_level=2,
            anchor=(owner, "effect:spiritual-weapon", f"cast:spiritual-weapon:{owner}"),
            cast_round=1,
        )

    _leave_roster(live, NEW, "zero_hp")

    assert [name for name in PURGED if NEW in getattr(live, name)] == []
    for identities in (live.conditions_by_effect, live.repeat_save_on_turn_end):
        assert not [key for key in identities if key[0] == NEW]
    assert live.help_grants == {"mon:a": [HERO]}
    assert live.vex_grants == {HERO: {"mon:a": 1}}
    assert live.sap_marks == {"mon:b": HERO}
    assert live.slow_marks == {"mon:a": {HERO}}
    assert [r.owner_id for r in live.pending_reactions] == [HERO]
    assert list(live.constructs) == [f"construct:{HERO}:spiritual-weapon"]
    assert live.concentration_chain[HERO] == [bless_on_new]
    assert held_other in live.conditions_by_effect
    assert held_other in live.repeat_save_on_turn_end


def test_monster_turn_start_runs_for_each_monster_after_a_mid_round_removal() -> None:
    # SRD 5.2 Recharge X–Y: "At the start of each of the monster's turns, roll
    # 1d6." The newcomer leaves during A's turn, so the Magma Mephit moves up
    # into the slot A's turn start ran for; a slot-keyed guard would skip its
    # roll.
    handle, live = start(
        [pc()],
        seed=1,
        encounter=[
            foe(entity_id="mon:a", name="A", initiative=15, zone_id=cell_id(5, 0)),
            foe(
                entity_id="mon:mephit",
                name="Mephit",
                initiative=10,
                hp_current=18,
                hp_max=18,
                ac=11,
                monster_template_slug="magma-mephit",
                zone_id=cell_id(7, 0),
            ),
        ],
    )
    _insert_into_roster(live, _newcomer(), 1, zone_id=NEW_ZONE)  # hero, newcomer, A, mephit
    live.monster_action_uses_by_entity["mon:mephit"]["fire-breath"].recharge_spent = True
    act(handle, HERO, intent_type="pass")
    act(handle, NEW, intent_type="pass")
    _run_monster_turn_start(live, _current_actor(live))  # A's turn starts
    _leave_roster(live, NEW, "zero_hp")
    _end_turn_and_advance(live, "mon:a")
    mephit = _current_actor(live)
    assert mephit.entity_id == "mon:mephit"
    assert live.current_turn_index == 2  # the slot A's turn start ran for
    _run_monster_turn_start(live, mephit)
    _run_monster_turn_start(live, mephit)  # the same creature and round: nothing
    rolled = events(live, RechargeRolled)
    assert [(e.monster_id, e.action_slug) for e in rolled] == [("mon:mephit", "fire-breath")]
    assert live.monster_turn_start_done == (1, "mon:mephit")


def test_primitives_draw_nothing() -> None:
    handle, live = _seated(2)  # hero, A, the newcomer, B, C
    act(handle, HERO, intent_type="pass")  # A is current
    state = live.rng.getstate()
    late = _newcomer().model_copy(update={"entity_id": "mon:late"})
    _insert_into_roster(live, late, 1, zone_id=NEW_ZONE)  # before the current actor
    _remove_from_roster(live, "mon:late")
    _end_turn_and_advance(live, "mon:a")  # the newcomer's turn opens
    _leave_roster(live, NEW, "zero_hp")  # the current actor leaves: B's turn opens
    assert _current_actor(live).entity_id == "mon:b"
    assert live.rng.getstate() == state
