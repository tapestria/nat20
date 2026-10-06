"""C21 — a summon's allegiance and its disappearance. SRD 5.2 Summon Dragon:
"The creature is an ally to you and your allies"; "The creature disappears
when it drops to 0 Hit Points or when the spell ends." A summon fights on
its owner's side without joining the side sets, so every path that reads
``party_ids`` / ``encounter_ids`` as "the PCs" / "the foes" is untouched,
and it leaves the initiative order at 0 Hit Points or when its caster's
concentration on the spell ends. The summons here are seated by hand
(``seat_summon``) on a seeded Summon Dragon anchor: no cast exists yet."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import pytest

from dnd5e_engine import ActiveEffect, CombatHandle
from dnd5e_engine.activities.passive_stats import CombatantSenses
from dnd5e_engine.events import (
    ActorMoved,
    AttackRolled,
    CheckRolled,
    CombatantLeft,
    ConcentrationCheck,
    ConcentrationDropped,
    ConditionApplied,
    DamageApplied,
    Death,
    EffectExpired,
    IntentSubmitted,
    MoveFailed,
    TurnEnded,
    TurnPhase,
    TurnStarted,
    Unconscious,
)
from dnd5e_engine.lib_loader import get_lib_loader
from dnd5e_engine.orchestrator import (
    IntentRejectedError,
    _allied_ids,
    _anchor_identity,
    _cleave_candidate,
    _current_actor,
    _emit,
    _get_live,
    _hostile_adjacent_to_attacker,
    _is_enemy,
    _LiveCombat,
    _pack_tactics_map,
    _side_of,
    _sneak_ally_adjacent_map,
    _target_help_advantage_map,
    _update_combatant,
    advance_monster_turn,
    end_combat,
    get_live,
    start_combat,
)
from dnd5e_engine.spatial import cell_id
from dnd5e_engine.specs import (
    EncounterMemberSpec,
    GridScene,
    PartyMemberSpec,
)
from dnd5e_engine.views import SummonView
from tests.c21_support import (
    act,
    anchor_effect,
    cleric,
    combatant,
    events,
    foe,
    monster_turn,
    pc,
    roster,
    seat_summon,
    start,
    summoner,
)

OWNER = "char:summoner"
SPIRIT = f"summon:{OWNER}:draconic-spirit:1"
ANCHOR = _anchor_identity("summon-dragon", OWNER)


def _summoned(
    *, seed: int = 1, hp: int = 50, encounter: list[EncounterMemberSpec] | None = None
) -> tuple[CombatHandle, _LiveCombat]:
    """The summoner at 0,0 concentrating on Summon Dragon, its spirit seated
    right after it at 0,1, and ``foe()`` at 1,0 (or ``encounter``) on the
    10x10 grid."""
    handle, live = start(
        [summoner()], seed=seed, encounter=encounter, active_effects=[anchor_effect(OWNER)]
    )
    seat_summon(live, OWNER, zone_id=cell_id(0, 1), hp=hp)
    return handle, live


def _begin(
    *,
    party: list[PartyMemberSpec],
    encounter: list[EncounterMemberSpec],
    seed: int = 1,
    **scene: Any,
) -> tuple[CombatHandle, _LiveCombat]:
    """Start on ``scene`` (``grid_scene=``) with the
    summoner's Summon Dragon anchor seeded."""
    result = asyncio.run(
        start_combat(
            session_id=f"c21b-allegiance-{seed}",
            party=party,
            encounter=encounter,
            rng_seed=seed,
            active_effects=[anchor_effect(OWNER)],
            **scene,
        )
    )
    return result.handle, _get_live(result.handle)


def test_a_summon_fights_on_its_owners_side() -> None:
    _, live = _summoned()
    assert _side_of(live, SPIRIT) is live.party_ids
    assert _is_enemy(live, "mon:foe", SPIRIT)
    assert _is_enemy(live, SPIRIT, "mon:foe")
    assert not _is_enemy(live, OWNER, SPIRIT)
    assert _allied_ids(live, OWNER) == _allied_ids(live, SPIRIT) == {OWNER, SPIRIT}
    assert _allied_ids(live, "mon:foe") == {"mon:foe"}
    assert _allied_ids(live, "mon:nobody") == set()


def test_summons_never_enter_the_side_sets_or_the_outcome() -> None:
    handle, live = _summoned(encounter=[foe(xp_value=100)])
    live.tracked_temp_hp[SPIRIT] = 5
    assert (live.party_ids, live.encounter_ids) == ({OWNER}, {"mon:foe"})
    _emit(
        live, DamageApplied(target_id="mon:foe", amount=500, damage_type="force", is_overkill=True)
    )
    outcome = asyncio.run(end_combat(handle)).outcome
    assert outcome.ended_reason == "victory"
    assert set(outcome.residual_hp) == {OWNER}
    assert SPIRIT not in outcome.residual_temp_hp
    assert outcome.xp_awarded == {OWNER: 100}
    assert [d.target_id for d in outcome.deaths] == ["mon:foe"]

    # A party whose members are all dead is a TPK even while a summon stands
    # (here one with no anchor, so its owner's death leaves it seated).
    handle, live = start(
        [summoner(hp_current=1, hp_max=1)],
        seed=2,
        encounter=[foe(attack_bonus=20, damage_dice="4d6")],
    )
    seat_summon(live, OWNER, zone_id=cell_id(0, 1))
    act(handle, OWNER, intent_type="pass")
    act(handle, SPIRIT, intent_type="pass")
    monster_turn(handle)  # the foe's lowest-HP target is the 1-HP summoner
    assert OWNER in live.dead_ids
    assert SPIRIT in roster(live)
    assert asyncio.run(end_combat(handle)).outcome.ended_reason == "defeat_tpk"


def _help_is_shared(live: _LiveCombat, handle: CombatHandle) -> None:
    # The spirit helps against the foe; after the foe's turn the summoner's
    # attack has Advantage from it and spends it.
    act(handle, OWNER, intent_type="pass")
    act(handle, SPIRIT, intent_type="help", target_id="mon:foe")
    monster_turn(handle)
    act(handle, OWNER, intent_type="attack", weapon_id="dagger", target_id="mon:foe")
    swing = [e for e in events(live, AttackRolled) if e.attacker_id == OWNER][-1]
    assert "help" in swing.sources
    assert "mon:foe" not in live.help_grants


def _help_follows_the_owner(live: _LiveCombat, handle: CombatHandle) -> None:
    # A summon attacking uses an ally's grant; a summon's grant never helps a foe.
    owner, spirit, enemy = (combatant(live, e) for e in (OWNER, SPIRIT, "mon:foe"))
    live.help_grants["mon:foe"] = [OWNER]
    live.help_grants[OWNER] = [SPIRIT]
    assert _target_help_advantage_map(live, SPIRIT, [enemy]) == {"mon:foe": True}
    assert _target_help_advantage_map(live, "mon:foe", [owner, spirit]) == {}


def _cleave_skips_the_summon(live: _LiveCombat, handle: CombatHandle) -> None:
    greataxe = get_lib_loader().get_weapon("greataxe")
    assert greataxe is not None
    assert greataxe.mastery == "cleave"
    owner, spirit, enemy = (combatant(live, e) for e in (OWNER, SPIRIT, "mon:foe"))
    assert _cleave_candidate(live, owner, greataxe, [enemy]) is None
    assert _cleave_candidate(live, enemy, greataxe, [owner]) == spirit


def _adjacency_counts_the_summon(live: _LiveCombat, handle: CombatHandle) -> None:
    owner, enemy = combatant(live, OWNER), combatant(live, "mon:foe")
    assert _sneak_ally_adjacent_map(live, owner, [enemy]) == {"mon:foe": True}
    assert _pack_tactics_map(live, owner, [enemy]) == {"mon:foe": True}
    assert _sneak_ally_adjacent_map(live, enemy, [owner]) == {}
    assert _pack_tactics_map(live, enemy, [owner]) == {}


def _a_summon_is_no_hostile_in_close_combat(live: _LiveCombat, handle: CombatHandle) -> None:
    live.actor_zone["mon:foe"] = cell_id(9, 9)  # only the spirit is within 5 ft
    assert _hostile_adjacent_to_attacker(live, combatant(live, OWNER)) is False
    assert _hostile_adjacent_to_attacker(live, combatant(live, SPIRIT)) is False
    live.actor_zone["mon:foe"] = cell_id(1, 1)
    assert _hostile_adjacent_to_attacker(live, combatant(live, SPIRIT)) is True


ALLY_SITES: dict[str, Callable[[_LiveCombat, CombatHandle], None]] = {
    "help": _help_is_shared,
    "help-maps": _help_follows_the_owner,
    "cleave": _cleave_skips_the_summon,
    "sneak-attack-and-pack-tactics": _adjacency_counts_the_summon,
    "ranged-in-close-combat": _a_summon_is_no_hostile_in_close_combat,
}


@pytest.mark.parametrize("site", list(ALLY_SITES))
def test_every_ally_site_treats_a_summon_as_its_owners_ally(site: str) -> None:
    handle, live = _summoned()
    ALLY_SITES[site](live, handle)


def test_hide_ignores_an_allied_summon_that_can_see_the_hider() -> None:
    # SRD 5.2 Hide: "you must be out of any enemy's line of sight". The
    # summoner hides in darkness beside its darkvision spirit; the foe can't
    # see into the dark.
    handle, live = _begin(
        party=[summoner()],
        encounter=[foe(zone_id=cell_id(5, 5))],
        grid_scene=GridScene(width=10, height=10, lighting={cell_id(0, 0): "dark"}),
    )
    seat_summon(live, OWNER, zone_id=cell_id(0, 1))
    combatant(live, SPIRIT).senses = CombatantSenses(darkvision=60)
    act(handle, OWNER, intent_type="hide")
    assert [e for e in events(live, CheckRolled) if e.skill == "stealth"]


def test_a_pc_can_path_through_its_summon_on_the_grid() -> None:
    # SRD 5.2: "you can pass through the space of an ally"; "You can't
    # willingly end a move in a space occupied by another creature."
    grid = GridScene(width=4, height=1)
    handle, live = _begin(
        party=[summoner()], encounter=[foe(zone_id=cell_id(3, 0))], grid_scene=grid
    )
    seat_summon(live, OWNER, zone_id=cell_id(1, 0))
    act(handle, OWNER, intent_type="move", target_zone_id=cell_id(1, 0))
    assert events(live, MoveFailed)[-1].reason == "occupied"
    act(handle, OWNER, intent_type="move", target_zone_id=cell_id(2, 0))
    assert events(live, ActorMoved)[-1].to_zone == cell_id(2, 0)
    assert live.actor_zone[OWNER] == cell_id(2, 0)


def test_a_summon_moving_on_the_grid_treats_foes_as_enemies() -> None:
    grid = GridScene(width=5, height=1)
    handle, live = _begin(
        party=[summoner(zone_id=cell_id(4, 0))],
        encounter=[foe(zone_id=cell_id(1, 0))],
        grid_scene=grid,
    )
    seat_summon(live, OWNER, zone_id=cell_id(0, 0))
    act(handle, OWNER, intent_type="pass")
    act(handle, SPIRIT, intent_type="move", target_zone_id=cell_id(2, 0))
    assert events(live, MoveFailed)[-1].reason == "unreachable"  # the foe's space blocks

    handle, live = _begin(
        party=[summoner(zone_id=cell_id(1, 0))],
        encounter=[foe(zone_id=cell_id(4, 0))],
        seed=2,
        grid_scene=grid,
    )
    seat_summon(live, OWNER, zone_id=cell_id(0, 0))
    act(handle, OWNER, intent_type="pass")
    act(handle, SPIRIT, intent_type="move", target_zone_id=cell_id(2, 0))
    assert events(live, ActorMoved)[-1].to_zone == cell_id(2, 0)  # through its owner


def test_a_foe_targets_a_summon_with_the_lowest_hp() -> None:
    handle, live = _summoned(hp=5, encounter=[foe(attack_bonus=5, damage_dice="1d4")])
    act(handle, OWNER, intent_type="pass")
    act(handle, SPIRIT, intent_type="pass")
    monster_turn(handle)
    submitted = [e for e in events(live, IntentSubmitted) if e.actor_id == "mon:foe"]
    assert [(e.intent_type, e.target_id) for e in submitted] == [("attack", SPIRIT)]
    assert [e.target_id for e in events(live, AttackRolled)] == [SPIRIT]


def test_zero_hp_removes_the_summon_without_a_death() -> None:
    handle, live = _summoned(hp=1, encounter=[foe(attack_bonus=20, damage_dice="1d4")])
    act(handle, OWNER, intent_type="pass")
    act(handle, SPIRIT, intent_type="pass")
    monster_turn(handle)
    assert events(live, CombatantLeft) == [CombatantLeft(entity_id=SPIRIT, reason="zero_hp")]
    assert SPIRIT not in roster(live)
    assert SPIRIT not in live.summons
    assert SPIRIT not in live.dead_ids
    assert not events(live, Death)
    assert not live.deaths_recorded
    assert not [e for e in events(live, Unconscious) if e.target_id == SPIRIT]
    assert not [e for e in events(live, ConditionApplied) if e.target_id == SPIRIT]
    assert live.concentration_chain[OWNER] == [ANCHOR]  # the caster keeps concentrating
    assert _current_actor(live).entity_id == OWNER  # round 2: nobody was skipped
    outcome = asyncio.run(end_combat(handle)).outcome
    assert (outcome.deaths, outcome.xp_awarded) == ([], {})


def test_a_hit_that_drops_a_summon_finishes_without_error() -> None:
    # SRD 5.2 Hill Giant Multiattack: "two attacks". The first swing drops
    # the 1-HP spirit; the second still resolves against its id, and the
    # giant's turn ends normally.
    giant = foe(
        entity_id="mon:giant",
        name="Giant",
        initiative=10,
        hp_current=105,
        hp_max=105,
        ac=13,
        monster_template_slug="hill-giant",
    )
    handle, live = _summoned(hp=1, encounter=[giant])
    _update_combatant(live, SPIRIT, ac=1)  # every swing that is no natural 1 hits
    act(handle, OWNER, intent_type="pass")
    act(handle, SPIRIT, intent_type="pass")
    monster_turn(handle)
    swings = [e for e in events(live, AttackRolled) if e.attacker_id == "mon:giant"]
    assert [e.target_id for e in swings] == [SPIRIT, SPIRIT]
    assert events(live, CombatantLeft) == [CombatantLeft(entity_id=SPIRIT, reason="zero_hp")]
    assert not events(live, Death)
    assert roster(live) == [OWNER, "mon:giant"]
    assert (_current_actor(live).entity_id, live.round_number) == (OWNER, 2)


def _drop_intent(live: _LiveCombat, handle: CombatHandle) -> None:
    act(handle, OWNER, intent_type="drop_concentration")


def _failed_con_save(live: _LiveCombat, handle: CombatHandle) -> None:
    act(handle, OWNER, intent_type="pass")
    act(handle, SPIRIT, intent_type="pass")
    monster_turn(handle)  # the foe hits the summoner; the CON save fails
    assert [e.succeeded for e in events(live, ConcentrationCheck) if e.target_id == OWNER] == [
        False
    ]


def _owners_death(live: _LiveCombat, handle: CombatHandle) -> None:
    # SRD 5.2 Massive Damage: the remainder equals or exceeds the Hit Point
    # maximum, so the summoner dies outright. Its concentration ends first:
    # the DC 30 Constitution save ("up to a maximum DC of 30") cannot succeed.
    _emit(live, DamageApplied(target_id=OWNER, amount=100, damage_type="force", is_overkill=True))
    assert OWNER in live.dead_ids


def _owners_incapacitation(live: _LiveCombat, handle: CombatHandle) -> None:
    _emit(live, ConditionApplied(target_id=OWNER, condition="incapacitated"))


def _duration_runs_out(live: _LiveCombat, handle: CombatHandle) -> None:
    # SRD 5.2 Summon Dragon: "Concentration, up to 1 hour" — its last round.
    live.concentration_rounds_remaining[OWNER] = 1
    act(handle, OWNER, intent_type="pass")


ANCHOR_ENDS: dict[str, tuple[Callable[[_LiveCombat, CombatHandle], None], str]] = {
    "drop-intent": (_drop_intent, "concentration_drop"),
    "failed-con-save": (_failed_con_save, "concentration_drop"),
    "owners-death": (_owners_death, "concentration_drop"),
    "owners-incapacitation": (_owners_incapacitation, "concentration_drop"),
    "duration": (_duration_runs_out, "spell_ended"),
}


@pytest.mark.parametrize("path", list(ANCHOR_ENDS))
def test_the_anchor_ending_dismisses_the_summon(path: str) -> None:
    end_anchor, reason = ANCHOR_ENDS[path]
    handle, live = _summoned(seed=3, encounter=[foe(attack_bonus=20, damage_dice="2d6")])
    end_anchor(live, handle)
    assert events(live, CombatantLeft) == [CombatantLeft(entity_id=SPIRIT, reason=reason)]
    expired = [
        e for e in events(live, EffectExpired) if (e.target_id, e.effect_id, e.origin) == ANCHOR
    ]
    assert len(expired) == 1
    assert live.event_log.index(expired[0]) < live.event_log.index(events(live, CombatantLeft)[0])
    assert SPIRIT not in roster(live)
    assert get_live(handle).summons == {}


def test_a_new_concentration_spell_dismisses_the_summon() -> None:
    # SRD 5.2 §Concentration: "You lose Concentration on an effect the moment
    # you start casting a spell that requires Concentration".
    handle, live = _summoned()
    act(handle, OWNER, intent_type="cast_spell", spell_id="fog-cloud", target_zone_id=cell_id(5, 5))
    assert events(live, CombatantLeft) == [
        CombatantLeft(entity_id=SPIRIT, reason="concentration_drop")
    ]
    assert live.concentration_chain[OWNER] == [_anchor_identity("fog-cloud", OWNER)]
    assert roster(live) == [OWNER, "mon:foe"]
    assert _current_actor(live).entity_id == "mon:foe"  # the cast ended the summoner's turn


def test_a_summon_dropped_on_its_own_move_hands_the_turn_on() -> None:
    # SRD 5.2 Opportunity Attacks: the foe beside the spirit strikes as it
    # leaves; at 0 Hit Points the spirit disappears mid-move. The spirit's
    # first step (1,0 -> 0,1) leaves the foe's (2,0) reach.
    handle, live = _begin(
        party=[summoner(zone_id=cell_id(0, 5))],
        encounter=[foe(zone_id=cell_id(2, 0), attack_bonus=20, damage_dice="2d6")],
        grid_scene=GridScene(width=10, height=10),
    )
    seat_summon(live, OWNER, zone_id=cell_id(1, 0), hp=1)
    act(handle, OWNER, intent_type="pass")
    assert _current_actor(live).entity_id == SPIRIT
    logged = len(live.event_log)
    act(handle, SPIRIT, intent_type="move", target_zone_id=cell_id(0, 2))
    tail = live.event_log[logged:]
    left = tail.index(CombatantLeft(entity_id=SPIRIT, reason="zero_hp"))
    assert tail[left + 1 : left + 4] == [
        TurnPhase(actor_id=SPIRIT, phase="turn_end", round_number=1),
        TurnEnded(actor_id=SPIRIT),
        TurnStarted(actor_id="mon:foe"),
    ]
    assert live.last_ended_turn == (1, SPIRIT)
    assert not [e for e in tail if isinstance(e, (ActorMoved, Death))]
    assert (roster(live), _current_actor(live).entity_id) == ([OWNER, "mon:foe"], "mon:foe")
    with pytest.raises(IntentRejectedError) as rejected:
        act(handle, SPIRIT, intent_type="pass")
    assert rejected.value.reason == "actor_not_in_initiative"


def test_a_legendary_action_that_drops_the_current_summon_opens_no_window() -> None:
    # SRD 5.2 Legendary Actions: taken "immediately after another creature's
    # turn" — here the summoner's, before its spirit acts. The spirit leaves
    # with no turn to end, so no window opens after it; the next creature's
    # turn opens once the legendary action has resolved. The lich's Deathly
    # Teleport (a 10-foot-radius burst) is placed by the engine's current
    # approximation — centred on an enemy, not on the space the lich leaves
    # (BACKLOG.md) — here on the spirit, which catches it and the ally beside
    # it and leaves the summoner (and its concentration) out of reach.
    lich = foe(
        entity_id="mon:lich",
        name="Lich",
        initiative=10,
        hp_current=256,
        hp_max=256,
        ac=19,
        monster_template_slug="lich",
        zone_id=cell_id(7, 3),
    )
    handle, live = start(
        [summoner(hp_current=90, hp_max=90), pc("char:ally", initiative=15, zone_id=cell_id(3, 5))],
        seed=1,
        encounter=[lich],
        active_effects=[anchor_effect(OWNER)],
    )
    seat_summon(live, OWNER, zone_id=cell_id(3, 3), hp=3)
    act(handle, OWNER, intent_type="pass")
    assert _current_actor(live).entity_id == SPIRIT
    first = len(live.event_log)
    asyncio.run(advance_monster_turn(handle, legendary=True))
    tail = live.event_log[first:]
    started = tail.index(TurnStarted(actor_id="char:ally"))
    assert CombatantLeft(entity_id=SPIRIT, reason="zero_hp") in tail[:started]
    assert [type(e) for e in tail[started:]] == [TurnStarted, TurnPhase]
    assert not [e for e in tail if isinstance(e, TurnEnded)]
    assert live.last_ended_turn == (1, OWNER)
    with pytest.raises(IntentRejectedError) as refused:
        asyncio.run(advance_monster_turn(handle, legendary=True))
    assert refused.value.reason == "no_legendary_action"


def test_every_reactor_still_reacts_after_a_summon_leaves_mid_loop() -> None:
    # The summoner walks away from two foes; the first opportunity attack
    # breaks its concentration and the spirit leaves mid-loop. The second
    # foe still strikes, and each spends its own Reaction. The summoner's one
    # step (1,1 -> 0,1) leaves both foes' (2,0 and 2,2) reach.
    handle, live = _begin(
        party=[summoner(zone_id=cell_id(1, 1))],
        encounter=[
            foe(
                entity_id="mon:one",
                name="One",
                initiative=15,
                zone_id=cell_id(2, 0),
                attack_bonus=20,
            ),
            foe(
                entity_id="mon:two",
                name="Two",
                initiative=10,
                zone_id=cell_id(2, 2),
                attack_bonus=20,
            ),
        ],
        grid_scene=GridScene(width=10, height=10),
    )
    seat_summon(live, OWNER, zone_id=cell_id(0, 5))
    act(handle, OWNER, intent_type="move", target_zone_id=cell_id(0, 1))
    reactions = [e.attacker_id for e in events(live, AttackRolled) if e.is_opportunity_attack]
    assert reactions == ["mon:one", "mon:two"]
    assert events(live, CombatantLeft) == [
        CombatantLeft(entity_id=SPIRIT, reason="concentration_drop")
    ]
    assert not combatant(live, "mon:one").reaction_available
    assert not combatant(live, "mon:two").reaction_available
    assert live.actor_zone[OWNER] == cell_id(0, 1)
    assert events(live, ConcentrationDropped)[0].target_id == OWNER


def test_a_departing_creatures_own_concentration_ends_with_it() -> None:
    # Whatever a departing creature concentrates on ends through the drop
    # cascade before it leaves, so none of its effects outlives it. A summon
    # casts no spell, so the spirit's own chain is seeded: a Resistance it
    # maintains on its summoner.
    handle, live = _summoned()
    origin = f"cast:resistance:{SPIRIT}"
    live.active_effects.setdefault(OWNER, []).append(
        ActiveEffect(
            id="effect:resistance",
            name="Resistance",
            origin=origin,
            target_id=OWNER,
            flags={"concentration": True},
        )
    )
    live.concentration_chain[SPIRIT] = [(OWNER, "effect:resistance", origin)]
    first = len(live.event_log)
    act(handle, OWNER, intent_type="drop_concentration")
    cascade = [
        (type(e).__name__, getattr(e, "target_id", None) or getattr(e, "entity_id", None))
        for e in live.event_log[first:]
        if isinstance(e, (ConcentrationDropped, EffectExpired, CombatantLeft))
    ]
    assert cascade == [
        ("ConcentrationDropped", OWNER),
        ("EffectExpired", OWNER),
        ("ConcentrationDropped", SPIRIT),
        ("EffectExpired", OWNER),
        ("CombatantLeft", SPIRIT),
    ]
    assert not [e for e in live.active_effects.get(OWNER, []) if e.origin == origin]
    assert SPIRIT not in live.concentration_chain


def test_a_concentration_on_a_departed_summon_still_ends() -> None:
    # The cleric's Bless on the spirit keeps running after the spirit leaves
    # at 0 Hit Points; ending it later names the departed id and raises nothing.
    handle, live = start(
        [summoner(), cleric(initiative=18, zone_id=cell_id(0, 2))],
        seed=1,
        encounter=[foe(attack_bonus=20, damage_dice="1d4")],
        active_effects=[anchor_effect(OWNER)],
    )
    seat_summon(live, OWNER, zone_id=cell_id(0, 1), hp=1)
    act(handle, OWNER, intent_type="pass")
    act(handle, SPIRIT, intent_type="pass")
    act(handle, "char:cleric", intent_type="cast_spell", spell_id="bless", target_id=SPIRIT)
    monster_turn(handle)  # the foe drops the 1-HP spirit
    assert events(live, CombatantLeft) == [CombatantLeft(entity_id=SPIRIT, reason="zero_hp")]
    act(handle, OWNER, intent_type="pass")
    act(handle, "char:cleric", intent_type="drop_concentration")
    assert [
        e.target_id for e in events(live, EffectExpired) if e.origin.endswith("char:cleric")
    ] == [SPIRIT]


def test_the_summons_view() -> None:
    handle, live = start([summoner()], seed=1)
    assert get_live(handle).summons == {}
    seat_summon(live, OWNER, zone_id=cell_id(0, 1))
    assert get_live(handle).summons == {
        SPIRIT: SummonView(
            entity_id=SPIRIT,
            owner_id=OWNER,
            spell_id="summon-dragon",
            stat_block_slug="draconic-spirit",
            slot_level=5,
        )
    }
    view = get_live(handle)
    assert [c.entity_id for c in view.initiative] == [OWNER, SPIRIT, "mon:foe"]
    assert SPIRIT not in view.party_ids | view.encounter_ids
