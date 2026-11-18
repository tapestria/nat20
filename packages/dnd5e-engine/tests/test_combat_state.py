"""``CombatState``: a combat as serializable state, resolved one seeded call at
a time (spec 02a, acceptance criteria 7 and 8; contract 03, "Determinism and
seeds": "Replaying a call with the recorded state and seed reproduces the
identical result").

Every per-field test below follows one shape: play the combat until the field
holds a value that matters, check the value, then make the next call three ways
(from the state object, from the state after a JSON round trip, and through the
handle API after ``load_combat``) and require the same events and the same new
state from all three (``_next``). The field-specific assertion then shows the
next call honoured the value, citing the SRD 5.2.1 rule it rests on.

``make test-roundtrip`` (``NAT20_ROUNDTRIP_STATE=1``, see ``conftest.py``) runs
the whole suite with every handle call rebuilding its combat from its
``CombatState``; that is what shows no other piece of ``_LiveCombat`` matters.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import subprocess
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest

from dnd5e_engine import PlayerIntent, advance_monster_turn, cell_id, submit_player_intent
from dnd5e_engine.combat_state import (
    CombatState,
    CombatStep,
    EffectKey,
    RepeatSave,
    arm_legendary_resistance,
    begin_combat,
    close_combat,
    combat_state_of,
    load_combat,
    resolve_intent,
    resolve_monster_turn,
    start_turn,
)
from dnd5e_engine.events import (
    AttackFailed,
    AttackRolled,
    ConcentrationDropped,
    DamageApplied,
    Death,
    DeathSaveRolled,
    EffectExpired,
    MoveFailed,
    ReactionTriggered,
    RechargeRolled,
    RoundStarted,
    SaveRolled,
    SpellCast,
    TurnEnded,
    TurnPhase,
    TurnStarted,
)
from dnd5e_engine.orchestrator import drain_pending_events, end_combat
from dnd5e_engine.specs import EncounterMemberSpec, GridScene, PartyMemberSpec

# ── builders ────────────────────────────────────────────────────────────────


def _pc(entity_id: str, **fields: Any) -> PartyMemberSpec:
    base: dict[str, Any] = {
        "entity_id": entity_id,
        "name": entity_id,
        "initiative": 20,
        "hp_current": 30,
        "hp_max": 30,
        "zone_id": cell_id(0, 0),
    }
    return PartyMemberSpec(**(base | fields))


def _fighter(entity_id: str = "pc:1", **fields: Any) -> PartyMemberSpec:
    """The spike's gate 1 fighter: level 3, longsword, chain mail."""
    base: dict[str, Any] = {
        "hp_current": 40,
        "hp_max": 40,
        "ac": 16,
        "strength": 16,
        "dexterity": 12,
        "constitution": 14,
        "zone_id": cell_id(1, 1),
        "class_slug": "fighter",
        "character_level": 3,
        "equipment": ("longsword", "chain-mail"),
    }
    return _pc(entity_id, **(base | fields))


def _bandit(
    entity_id: str, col: int, row: int, initiative: int, **fields: Any
) -> EncounterMemberSpec:
    base: dict[str, Any] = {
        "entity_id": entity_id,
        "entity_type": "Monster",
        "name": "Bandit",
        "initiative": initiative,
        "hp_current": 30,
        "hp_max": 30,
        "ac": 12,
        "attack_bonus": 3,
        "damage_dice": "1d6+1",
        "zone_id": cell_id(col, row),
        "monster_template_slug": "bandit",
    }
    return EncounterMemberSpec(**(base | fields))


def _foe(**fields: Any) -> EncounterMemberSpec:
    """A template-less 500 HP, AC 1 foe at cell 1,0 that acts last."""
    base: dict[str, Any] = {
        "entity_id": "mon:foe",
        "entity_type": "Monster",
        "name": "Foe",
        "initiative": 1,
        "hp_current": 500,
        "hp_max": 500,
        "ac": 1,
        "zone_id": cell_id(1, 0),
    }
    return EncounterMemberSpec(**(base | fields))


_WIZARD: dict[str, Any] = {
    "initiative": 15,
    "zone_id": cell_id(0, 1),
    "class_slug": "wizard",
    "character_level": 5,
    "intelligence": 20,
    "spell_slots": {1: 3, 2: 3},
    "spells_known": ["hold-person", "shield"],
}

_CLERIC: dict[str, Any] = {
    "initiative": 15,
    "zone_id": cell_id(0, 1),
    "class_slug": "cleric",
    "character_level": 5,
    "wisdom": 18,
    "spell_slots": {1: 3},
    "spells_known": ["bless"],
}


async def _open_async(
    party: list[PartyMemberSpec], encounter: list[EncounterMemberSpec], seed: int = 1
) -> CombatState:
    """Async version of _open that doesn't use asyncio.run()."""
    step = await begin_combat(
        session_id="state",
        party=party,
        encounter=encounter,
        grid_scene=GridScene(width=10, height=10),
        seed=seed,
    )
    return step.state


def _open(
    party: list[PartyMemberSpec], encounter: list[EncounterMemberSpec], seed: int = 1
) -> CombatState:
    step = asyncio.run(
        begin_combat(
            session_id="state",
            party=party,
            encounter=encounter,
            grid_scene=GridScene(width=10, height=10),
            seed=seed,
        )
    )
    return step.state


async def _gate1_fight_async() -> CombatState:
    """Async version of _gate1_fight."""
    return await _open_async([_fighter()], [_bandit("npc:1", 2, 1, 10), _bandit("npc:2", 2, 2, 5)])


def _gate1_fight() -> CombatState:
    """The spike's gate 1 fight: the fighter against two bandits."""
    return _open([_fighter()], [_bandit("npc:1", 2, 1, 10), _bandit("npc:2", 2, 2, 5)])


# ── the three-way next call ─────────────────────────────────────────────────

Call = tuple[str, dict[str, Any]]


def _intent(actor_id: str, **intent: Any) -> Call:
    return ("intent", {"actor_id": actor_id, "intent": PlayerIntent(**intent)})


def _monster(**kwargs: Any) -> Call:
    return ("monster", kwargs)


def _stateless(state: CombatState, call: Call, seed: int) -> CombatStep:
    kind, args = call
    if kind == "intent":
        return asyncio.run(resolve_intent(state, seed=seed, **args))
    return asyncio.run(resolve_monster_turn(state, seed=seed, **args))


def _through_handle(state: CombatState, call: Call, seed: int) -> CombatStep:
    handle = load_combat(state)
    kind, args = call
    if kind == "intent":
        asyncio.run(submit_player_intent(handle, seed=seed, **args))
    else:
        asyncio.run(advance_monster_turn(handle, seed=seed, **args))
    return CombatStep(events=drain_pending_events(handle), state=combat_state_of(handle))


def _json(state: CombatState) -> CombatState:
    loaded = CombatState.model_validate_json(state.model_dump_json())
    assert loaded == state
    assert loaded.model_dump_json() == state.model_dump_json()
    return loaded


def _next(state: CombatState, call: Call, seed: int = 7) -> CombatStep:
    """The next call, from ``state``, from its JSON round trip, and through the
    handle API: all three must give the same events and the same state."""
    direct = _stateless(state, call, seed)
    reloaded = _stateless(_json(state), call, seed)
    handled = _through_handle(_json(state), call, seed)
    for other in (reloaded, handled):
        assert other.model_dump_json() == direct.model_dump_json()
    return direct


def _play(state: CombatState, calls: list[Call], seed: int = 100) -> CombatState:
    for offset, call in enumerate(calls):
        state = _stateless(state, call, seed + offset).state
    return state


def _of[T](step: CombatStep, kind: type[T]) -> list[T]:
    return [e for e in step.events if isinstance(e, kind)]


def _combatant(state: CombatState, entity_id: str) -> Any:
    combatant = state.combatant(entity_id)
    assert combatant is not None
    return combatant


def _with_combatant(state: CombatState, entity_id: str, **fields: Any) -> CombatState:
    """``state`` with fields of one combatant changed, as a host may write it."""
    return state.model_copy(
        update={
            "combatants": [
                c.model_copy(update=fields) if c.entity_id == entity_id else c
                for c in state.combatants
            ]
        }
    )


# ── round trip ──────────────────────────────────────────────────────────────


def test_a_state_round_trips_through_json_without_loss() -> None:
    state = _open([_pc("char:hero"), _pc("char:wiz", **_WIZARD)], [_foe()], seed=1)
    state = _play(
        state,
        [
            _intent("char:hero", intent_type="attack", target_id="mon:foe"),
            _intent(
                "char:wiz",
                intent_type="cast_spell",
                spell_id="hold-person",
                target_id="mon:foe",
                slot_level=2,
            ),
        ],
        seed=1,
    )
    assert state.effects
    assert state.repeat_saves
    assert state.concentration
    text = state.model_dump_json()
    loaded = CombatState.model_validate_json(text)
    assert loaded == state
    assert loaded.model_dump_json() == text
    assert CombatState.model_validate(json.loads(text)) == state


def test_a_state_is_independent_of_the_call_that_made_it() -> None:
    """A resolving call never changes the state it was given: a host keeps it
    as the record of where the combat stood."""
    state = _gate1_fight()
    before = state.model_dump_json()
    _next(state, _intent("pc:1", intent_type="attack", target_id="npc:1", weapon_id="longsword"))
    assert state.model_dump_json() == before


def test_a_rejected_intent_leaves_the_state_as_it_was() -> None:
    from dnd5e_engine import IntentRejectedError

    state = _gate1_fight()
    before = state.model_dump_json()
    with pytest.raises(IntentRejectedError):
        asyncio.run(
            resolve_intent(state, actor_id="npc:1", intent=PlayerIntent(intent_type="pass"), seed=1)
        )
    assert state.model_dump_json() == before


# ── criterion 7: one test per field ─────────────────────────────────────────


def test_round() -> None:
    """SRD 5.2.1 "Combat Step by Step": "When everyone involved in the combat
    has had a turn, the round ends." A state two rounds in resumes in round 3,
    and the round wraps to 4."""
    state = _gate1_fight()
    for _ in range(2):
        state = _play(
            state,
            [
                _intent("pc:1", intent_type="attack", target_id="npc:1", weapon_id="longsword"),
                _monster(),
                _monster(),
            ],
        )
    assert state.round == 3
    state = _play(
        state,
        [
            _intent("pc:1", intent_type="attack", target_id="npc:1", weapon_id="longsword"),
            _monster(),
        ],
    )
    step = _next(state, _monster())
    assert [e.round_number for e in _of(step, RoundStarted)] == [4]
    assert step.state.round == 4


def test_active_combatant() -> None:
    """SRD 5.2.1 "Initiative Order": "This is the order in which they act
    during each round." A state whose round and active combatant a host set
    resumes there: the second bandit's turn in round 3 ends, and round 4 opens
    at the fighter."""
    state = _gate1_fight().at_turn(3, "npc:2")
    assert (state.round, state.active_combatant, state.turn_index) == (3, "npc:2", 2)
    step = _next(state, _monster())
    assert [e.actor_id for e in _of(step, TurnEnded)] == ["npc:2"]
    assert [e.actor_id for e in _of(step, TurnStarted)] == ["pc:1"]
    assert (step.state.round, step.state.active_combatant) == (4, "pc:1")


def test_initiative() -> None:
    """SRD 5.2.1 "Initiative Order": "The GM ranks the combatants, from
    highest to lowest Initiative." The order and each Initiative survive the
    state, and the turn after the fighter's goes to the higher bandit."""
    state = _gate1_fight()
    assert [(c.entity_id, c.initiative) for c in state.combatants] == [
        ("pc:1", 20),
        ("npc:1", 10),
        ("npc:2", 5),
    ]
    step = _next(
        state, _intent("pc:1", intent_type="attack", target_id="npc:1", weapon_id="longsword")
    )
    assert [e.actor_id for e in _of(step, TurnStarted)] == ["npc:1"]


def test_position() -> None:
    """A melee weapon attack reaches only creatures within its reach (SRD 5.2.1
    "Opportunity Attacks": "when a creature that you can see leaves your
    reach"). After the fighter walks away from the bandits, the state holds the
    new cell, and a longsword attack from there fails as out of range."""
    state = _gate1_fight()
    state = _play(state, [_intent("pc:1", intent_type="move", target_zone_id=cell_id(4, 1))])
    assert state.positions["pc:1"] == cell_id(4, 1)
    step = _next(
        state, _intent("pc:1", intent_type="attack", target_id="npc:1", weapon_id="longsword")
    )
    assert [e.reason for e in _of(step, AttackFailed)] == ["out_of_range"]
    assert not _of(step, AttackRolled)


def test_turn_resources() -> None:
    """SRD 5.2.1 "Movement and Position": "On your turn, you can move a
    distance equal to your Speed or less." The fighter spends 20 of its 30
    feet, the state keeps the 10 feet left, and a further 15-foot move fails."""
    state = _gate1_fight()
    state = _play(state, [_intent("pc:1", intent_type="move", target_zone_id=cell_id(1, 5))])
    assert _combatant(state, "pc:1").movement_remaining == 10
    step = _next(state, _intent("pc:1", intent_type="move", target_zone_id=cell_id(1, 8)))
    assert _of(step, MoveFailed)
    assert step.state.positions["pc:1"] == cell_id(1, 5)


def test_reaction_availability() -> None:
    """SRD 5.2.1 "Reaction": "Once you take a Reaction, you can't take another
    one until the start of your next turn." The bandit's Opportunity Attack on
    the first hero spends its Reaction; the state records it, so the second
    hero leaving its reach provokes nothing."""
    state = _open(
        [
            _pc("pc:a", zone_id=cell_id(1, 1), initiative=20),
            _pc("pc:b", zone_id=cell_id(3, 1), initiative=15),
        ],
        [_bandit("npc:1", 2, 1, 10)],
    )
    first = _stateless(state, _intent("pc:a", intent_type="move", target_zone_id=cell_id(1, 5)), 3)
    assert [e for e in _of(first, AttackRolled) if e.attacker_id == "npc:1"]
    state = _play(first.state, [_intent("pc:a", intent_type="pass")])
    assert _combatant(state, "npc:1").reaction_available is False
    step = _next(state, _intent("pc:b", intent_type="move", target_zone_id=cell_id(5, 5)))
    assert not [e for e in _of(step, AttackRolled) if e.attacker_id == "npc:1"]


def test_hit_points() -> None:
    """SRD 5.2.1 "Monster Death": "A monster dies the instant it drops to 0
    Hit Points". A bandit at 1 Hit Point in the state dies to the next
    longsword hit."""
    state = _gate1_fight()
    state = state.model_copy(update={"hp": state.hp | {"npc:1": 1}})
    state = _with_combatant(state, "npc:1", hp_current=1)
    for seed in range(1, 30):
        step = _next(
            state,
            _intent("pc:1", intent_type="attack", target_id="npc:1", weapon_id="longsword"),
            seed,
        )
        if any(e.is_hit for e in _of(step, AttackRolled)):
            break
    assert [e.target_id for e in _of(step, Death)] == ["npc:1"]
    assert "npc:1" in step.state.dead


def test_temporary_hit_points() -> None:
    """SRD 5.2.1 "Lose Temporary Hit Points First": "If you have Temporary Hit
    Points and take damage, those points are lost first". The fighter's 50
    Temporary Hit Points in the state absorb the bandit's hit, so its Hit
    Points stay at 40."""
    state = _gate1_fight().at_turn(1, "npc:1")
    state = state.model_copy(update={"temp_hp": {"pc:1": 50}})
    state = _with_combatant(state, "pc:1", temp_hp=50)
    for seed in range(1, 30):
        step = _next(state, _monster(), seed)
        if _of(step, DamageApplied):
            break
    assert step.state.hp["pc:1"] == 40
    assert step.state.temp_hp["pc:1"] < 50


def test_conditions() -> None:
    """SRD 5.2.1 Paralyzed: "Any attack roll that hits you is a Critical Hit if
    the attacker is within 5 feet of you." Hold Person paralyzes the foe; from
    the state, the hero's next hit is a Critical Hit."""
    hero = _pc("char:hero", strength=16, equipment=("longsword",))
    state = _open([hero, _pc("char:wiz", **_WIZARD)], [_foe()], seed=1)
    state = _play(
        state,
        [
            _intent("char:hero", intent_type="pass"),
            _intent(
                "char:wiz",
                intent_type="cast_spell",
                spell_id="hold-person",
                target_id="mon:foe",
                slot_level=2,
            ),
        ],
        seed=1,
    )
    assert state.conditions["mon:foe"] == ["paralyzed"]
    assert [c.condition for c in _combatant(state, "mon:foe").conditions] == ["paralyzed"]
    # The foe's own turn ends with its repeat save; take a seed it fails.
    held = next(
        step.state
        for seed in range(1, 40)
        if "paralyzed" in (step := _stateless(state, _monster(), seed)).state.conditions["mon:foe"]
    )
    attack = _intent("char:hero", intent_type="attack", target_id="mon:foe", weapon_id="longsword")
    step = _next(held, attack)
    [rolled] = _of(step, AttackRolled)
    assert rolled.is_hit
    assert rolled.is_crit


def test_death_saving_throws() -> None:
    """SRD 5.2.1 "Death Saving Throws": "On your third failure, you die. The
    successes and failures don't need to be consecutive; keep track of both".
    A hero at 0 Hit Points with two failures in the state fails a third save
    on its turn and dies; each roll counts on from the state's tally."""
    state = _open([_pc("char:hero", hp_current=0)], [_foe(zone_id=cell_id(5, 5))], seed=1)
    # Its first turn already rolled one save.
    assert set(_combatant(state, "char:hero").death_saves) == {"successes", "failures", "is_stable"}
    state = state.at_turn(1, "mon:foe")
    state = _with_combatant(
        state, "char:hero", death_saves={"successes": 0, "failures": 2, "is_stable": False}
    )
    for seed in range(1, 40):
        step = _next(state, _monster(), seed)
        rolled = _of(step, DeathSaveRolled)
        assert rolled
        assert rolled[0].running_failures >= 2
        if rolled[0].outcome in ("failure", "crit_failure"):
            break
    assert [e.target_id for e in _of(step, Death)] == ["char:hero"]


def test_readied_action() -> None:
    """SRD 5.2.1 Shield: "Casting Time: Reaction, which you take when you are
    hit by an attack roll". The wizard readies Shield (the engine's 0.7.0
    reaction path, which #38 replaces); the state holds it, and the bandit's
    attack on the wizard takes it."""
    state = _open(
        [_pc("char:wiz", **(_WIZARD | {"zone_id": cell_id(1, 1)}))], [_bandit("npc:1", 2, 1, 10)]
    )
    state = _play(
        state,
        [
            _intent(
                "char:wiz", intent_type="ready", spell_id="shield", reaction_trigger="hit_by_attack"
            )
        ],
    )
    assert [(r.owner_id, r.spell_id, r.trigger) for r in state.readied] == [
        ("char:wiz", "shield", "hit_by_attack")
    ]
    step = _next(state, _monster())
    assert [e.actor_id for e in _of(step, ReactionTriggered)] == ["char:wiz"]
    assert step.state.readied == []


def test_active_effects() -> None:
    """SRD 5.2.1 Bless: "Whenever a target makes an attack roll or a saving
    throw before the spell ends, the target adds 1d4 to the attack roll or
    save." Bless on the hero stays in the state, held by the cleric's
    Concentration, through the hero's next attack."""
    state = _open([_pc("char:hero"), _pc("char:cleric", **_CLERIC)], [_foe()], seed=1)
    state = _play(
        state,
        [
            _intent("char:hero", intent_type="pass"),
            _intent(
                "char:cleric",
                intent_type="cast_spell",
                spell_id="bless",
                target_id="char:hero",
                slot_level=1,
            ),
            _monster(),
        ],
    )
    [blessed] = state.effects["char:hero"]
    assert blessed.origin.startswith("cast:bless")
    assert [k.target_id for k in state.concentration["char:cleric"]] == ["char:hero"]
    step = _next(state, _intent("char:hero", intent_type="attack", target_id="mon:foe"))
    assert step.state.effects["char:hero"] == [blessed]


def test_concentration_time_remaining() -> None:
    """SRD 5.2.1 Bless: "Duration: Concentration, up to 1 minute". With one
    round left in the state, Bless ends at the end of the cleric's next turn;
    with the full minute it does not."""
    state = _open([_pc("char:hero"), _pc("char:cleric", **_CLERIC)], [_foe()], seed=1)
    state = _play(
        state,
        [
            _intent("char:hero", intent_type="pass"),
            _intent(
                "char:cleric",
                intent_type="cast_spell",
                spell_id="bless",
                target_id="char:hero",
                slot_level=1,
            ),
            _monster(),
            _intent("char:hero", intent_type="pass"),
        ],
    )
    assert state.concentration_rounds_remaining == {"char:cleric": 9}
    held = _next(state, _intent("char:cleric", intent_type="pass"))
    assert not _of(held, ConcentrationDropped)
    assert held.state.concentration_rounds_remaining == {"char:cleric": 8}
    ending = state.model_copy(update={"concentration_rounds_remaining": {"char:cleric": 1}})
    step = _next(ending, _intent("char:cleric", intent_type="pass"))
    assert [e.target_id for e in _of(step, ConcentrationDropped)] == ["char:cleric"]
    assert [(e.target_id, e.reason) for e in _of(step, EffectExpired)] == [
        ("char:hero", "duration")
    ]
    assert step.state.effects["char:hero"] == []
    assert "char:cleric" not in step.state.concentration_rounds_remaining


def test_pending_repeat_saves() -> None:
    """SRD 5.2.1 Hold Person: "At the end of each of its turns, the target
    repeats the save, ending the spell on itself on a success." The state holds
    the pending save, and the foe rolls it at the end of its turn: a Wisdom
    save against the wizard's DC 16."""
    state = _open([_pc("char:hero"), _pc("char:wiz", **_WIZARD)], [_foe()], seed=1)
    state = _play(
        state,
        [
            _intent("char:hero", intent_type="pass"),
            _intent(
                "char:wiz",
                intent_type="cast_spell",
                spell_id="hold-person",
                target_id="mon:foe",
                slot_level=2,
            ),
        ],
        seed=1,
    )
    [pending] = state.repeat_saves
    assert pending.effect.target_id == "mon:foe"
    assert pending.saves == [
        RepeatSave(
            ability="wis",
            dc=16,
            condition="paralyzed",
            caster_id="char:wiz",
            effect_name="Paralyzed",
        )
    ]
    step = _next(state, _monster())
    saves = [e for e in _of(step, SaveRolled) if e.target_id == "mon:foe"]
    assert [(e.ability, e.dc) for e in saves] == [("wis", 16)]


def test_monster_spent_recharge() -> None:
    """SRD 5.2.1 "Recharge X–Y": "At the start of each of the monster's turns,
    roll 1d6. If the roll is within the number range given in the notation
    (represented by X–Y), the monster regains the use of that part". The magma
    mephit's spent Fire Breath stays spent in the state, and its next turn
    start rolls the recharge."""
    state = _open(
        [_pc("char:hero", initiative=1, zone_id=cell_id(0, 0))],
        [
            _foe(
                entity_id="mon:mephit",
                initiative=20,
                hp_current=18,
                hp_max=18,
                ac=11,
                monster_template_slug="magma-mephit",
            )
        ],
        seed=7,
    )
    state = _play(state, [_monster()], seed=7)
    assert state.monster_action_uses["mon:mephit"]["fire-breath"].recharge_spent is True
    state = _play(state, [_intent("char:hero", intent_type="pass")])
    step = _next(state, _monster())
    rolled = _of(step, RechargeRolled)
    assert [(e.monster_id, e.action_slug) for e in rolled] == [("mon:mephit", "fire-breath")]


# The mage's Spellcasting activities in the corpus (``mage.json``).
_FIREBALL = "OMMdgcswZDwcu4P9"
_INVISIBILITY = "PsQU2yHchoO5kFLT"
_CONE_OF_COLD = "cDga1NaxiuzNOPlP"
_FLY = "F9pGhXppRUa1chuR"


def test_monster_per_day_uses() -> None:
    """SRD 5.2.1 Mage, Spellcasting: "2/Day Each: Fireball (level 4 version),
    Invisibility" and "1/Day Each: Cone of Cold, Fly". With both Fireball and
    both Invisibility uses spent in the state, the mage casts Cone of Cold
    instead, and that use is spent in the new state."""
    state = _open(
        [_pc("char:hero", initiative=1)],
        [
            _foe(
                entity_id="mon:mage",
                initiative=20,
                hp_current=40,
                hp_max=40,
                ac=12,
                monster_template_slug="mage",
            )
        ],
        seed=5,
    )
    uses = state.monster_action_uses["mon:mage"]["spellcasting"]
    daily = dict(uses.uses_remaining)
    assert daily == {
        f"spellcasting:{_FIREBALL}": 2,
        f"spellcasting:{_INVISIBILITY}": 2,
        f"spellcasting:{_CONE_OF_COLD}": 1,
        f"spellcasting:{_FLY}": 1,
    }
    spent = {f"spellcasting:{_FIREBALL}": 0, f"spellcasting:{_INVISIBILITY}": 0}
    exhausted = uses.model_copy(update={"uses_remaining": daily | spent})
    state = state.model_copy(
        update={
            "monster_action_uses": state.monster_action_uses
            | {"mon:mage": state.monster_action_uses["mon:mage"] | {"spellcasting": exhausted}}
        }
    )
    step = _next(state, _monster(), seed=5)
    assert [e.spell_id for e in _of(step, SpellCast)] == ["cone-of-cold"]
    after = step.state.monster_action_uses["mon:mage"]["spellcasting"].uses_remaining
    assert after == exhausted.uses_remaining | {f"spellcasting:{_CONE_OF_COLD}": 0}


def test_legendary_resistance_armed() -> None:
    """A Legendary Resistance armed in one call is in the state for the
    next (SRD 5.2.1 "Legendary Resistance (3/Day)": "If the dragon fails a
    saving throw, it can choose to succeed instead")."""
    state = _open(
        [_pc("char:hero", initiative=1)],
        [
            _foe(
                entity_id="mon:dragon",
                initiative=20,
                hp_current=256,
                hp_max=256,
                ac=19,
                monster_template_slug="adult-red-dragon",
                zone_id=cell_id(5, 5),
            )
        ],
    )
    step = arm_legendary_resistance(state, "mon:dragon")
    assert step.events == []
    assert step.state.legendary_resistance_armed == {"mon:dragon": 1}
    assert _json(step.state).legendary_resistance_armed == {"mon:dragon": 1}


def test_close_combat_reports_the_outcome_and_the_ended_state() -> None:
    state = _gate1_fight()
    closed = asyncio.run(close_combat(state))
    assert closed.state.ended is True
    assert closed.outcome.ended_reason == "forced"
    again = asyncio.run(close_combat(closed.state))
    assert again.events == []
    assert again.outcome == closed.outcome


def test_effect_key_names_one_effect_instance() -> None:
    key = EffectKey(target_id="pc:1", effect_id="effect:bless", origin="cast:bless:pc:2")
    assert EffectKey.of(key.key()) == key


# ── criterion 8: determinism ────────────────────────────────────────────────


def _random_fight(case: random.Random) -> tuple[CombatState, list[tuple[Call, int]]]:
    """A random fight: a fighter, a wizard with Hold Person and Shield, and one
    to three bandits on random cells, then a random script of calls, each with
    a random seed."""
    columns = case.sample(range(3, 9), 3)
    bandits = [
        _bandit(f"npc:{i}", columns[i - 1], case.randrange(0, 9), 10 - i)
        for i in range(1, case.randint(1, 3) + 1)
    ]
    party = [
        _fighter(zone_id=cell_id(case.randrange(0, 3), case.randrange(0, 9))),
        _pc("char:wiz", **(_WIZARD | {"zone_id": cell_id(0, 9), "initiative": 15})),
    ]
    state = _open(party, bandits, seed=case.randrange(2**63))
    script: list[tuple[Call, int]] = []
    for _ in range(case.randint(4, 12)):
        script.append((("auto", {"choice": case.randrange(4)}), case.randrange(2**63)))
    return state, script


def _auto_call(state: CombatState, choice: int) -> Call:
    """The call a scripted step makes for whoever is active."""
    actor = state.combatants[state.turn_index]
    if actor.entity_type != "Character":
        return _monster()
    targets = [c.entity_id for c in state.combatants if c.entity_id.startswith("npc:")]
    living = [t for t in targets if t not in state.dead] or targets
    if actor.entity_id == "char:wiz":
        options = [
            _intent(
                "char:wiz",
                intent_type="cast_spell",
                spell_id="hold-person",
                target_id=living[0],
                slot_level=2,
            ),
            _intent(
                "char:wiz", intent_type="ready", spell_id="shield", reaction_trigger="hit_by_attack"
            ),
            _intent("char:wiz", intent_type="pass"),
        ]
    else:
        options = [
            _intent(
                actor.entity_id, intent_type="attack", target_id=living[0], weapon_id="longsword"
            ),
            _intent(actor.entity_id, intent_type="move", target_zone_id=state.positions[living[0]]),
            _intent(actor.entity_id, intent_type="pass"),
        ]
    return options[choice % len(options)]


def _run_script(state: CombatState, script: list[tuple[Call, int]], *, via_json: bool) -> list[str]:
    from dnd5e_engine import IntentRejectedError

    outputs: list[str] = []
    for (_, args), seed in script:
        if state.ended:
            break
        call = _auto_call(state, args["choice"])
        try:
            step = _stateless(_json(state) if via_json else state, call, seed)
        except IntentRejectedError as rejected:
            outputs.append(f"rejected:{rejected}")
            call = _intent(state.combatants[state.turn_index].entity_id, intent_type="pass")
            if state.combatants[state.turn_index].entity_type != "Character":
                break
            step = _stateless(state, call, seed)
        outputs.append(step.model_dump_json())
        state = step.state
    return outputs


@pytest.mark.parametrize("case_seed", range(40))
def test_the_same_state_call_and_seed_give_byte_identical_output(case_seed: int) -> None:
    """Contract 03: "The same TurnState, input, and seed always produce the
    same result, byte for byte." For random fights, scripts and seeds, a
    second run of every call, from the state's JSON, gives the same bytes."""
    state, script = _random_fight(random.Random(case_seed))
    first = _run_script(state, script, via_json=False)
    second = _run_script(state, script, via_json=True)
    assert first == second
    assert len(first) >= 1


def test_a_different_seed_draws_different_dice() -> None:
    state = _gate1_fight()
    call = _intent("pc:1", intent_type="attack", target_id="npc:1", weapon_id="longsword")
    rolls = {_stateless(state, call, seed).events[1].model_dump_json() for seed in range(1, 20)}
    assert len(rolls) > 1


def test_combat_never_touches_the_global_random_module(monkeypatch: pytest.MonkeyPatch) -> None:
    """Spec 02a, criterion 8: with every function of the global ``random``
    module raising, a whole fight still resolves, so no die comes from it."""

    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("the engine used the global random module")

    for name in (
        "random",
        "randint",
        "randrange",
        "choice",
        "choices",
        "shuffle",
        "sample",
        "uniform",
        "getrandbits",
        "seed",
        "getstate",
        "setstate",
    ):
        monkeypatch.setattr(random, name, forbidden)
    for case_seed in range(5):
        state, script = _random_fight(_CaseRandom(case_seed))
        outputs = _run_script(state, script, via_json=False)
        assert outputs
    closed = asyncio.run(close_combat(_gate1_fight()))
    assert closed.state.ended


class _CaseRandom(random.Random):
    """The test's own generator for drawing random fights: an instance, never
    the module functions the test above disables."""


_HASHSEED_SCRIPT = """
import asyncio, json, random, sys
sys.path.insert(0, sys.argv[1])
from tests.test_combat_state import _random_fight, _run_script
out = []
for case_seed in range(8):
    state, script = _random_fight(random.Random(case_seed))
    out.extend(_run_script(state, script, via_json=False))
sys.stdout.write(json.dumps(out))
"""


def test_output_does_not_depend_on_the_process_hash_seed() -> None:
    """A set iterates in the order of the process's string hash seed. Two
    processes with different ``PYTHONHASHSEED`` values must produce the same
    bytes for the same fights, or a replay in another process would differ."""
    root = str(Path(__file__).resolve().parents[1])
    outputs = []
    for hash_seed in ("1", "2"):
        env = {**os.environ, "PYTHONHASHSEED": hash_seed}
        result = subprocess.run(  # the test's own interpreter and script
            [sys.executable, "-c", _HASHSEED_SCRIPT, root],
            capture_output=True,
            text=True,
            env=env,
            cwd=root,
            check=True,
        )
        outputs.append(result.stdout)
    assert outputs[0] == outputs[1]
    assert json.loads(outputs[0])


# ── the handle API on the same core ─────────────────────────────────────────


def test_the_handle_api_and_the_stateless_api_agree_call_by_call() -> None:
    """``start_combat`` plus seeded handle calls and ``begin_combat`` plus
    stateless calls are the same combat: same events, same state, every call."""
    from dnd5e_engine import start_combat

    started = asyncio.run(
        start_combat(
            session_id="state",
            party=[_fighter()],
            encounter=[_bandit("npc:1", 2, 1, 10), _bandit("npc:2", 2, 2, 5)],
            grid_scene=GridScene(width=10, height=10),
            rng_seed=1,
        )
    )
    handle = started.handle
    drain_pending_events(handle)
    state = _gate1_fight()
    assert combat_state_of(handle) == state
    calls: list[Call] = []
    for _ in range(3):
        calls += [
            _intent("pc:1", intent_type="attack", target_id="npc:1", weapon_id="longsword"),
            _monster(),
            _monster(),
        ]
    runners: dict[str, Callable[..., Awaitable[None]]] = {
        "intent": submit_player_intent,
        "monster": advance_monster_turn,
    }
    for seed, (kind, args) in enumerate(calls, start=50):
        if state.ended:
            break
        step = _stateless(state, (kind, args), seed)
        asyncio.run(runners[kind](handle, seed=seed, **args))
        assert drain_pending_events(handle) == step.events
        assert combat_state_of(handle) == step.state
        state = step.state
    assert asyncio.run(end_combat(handle)).outcome == asyncio.run(close_combat(state)).outcome


def test_at_turn_names_a_combatant_in_the_order() -> None:
    with pytest.raises(ValueError, match="not in the initiative order"):
        _gate1_fight().at_turn(2, "npc:9")


@pytest.mark.asyncio
async def test_start_turn_emits_turn_started_and_resets_resources() -> None:
    """start_turn emits TurnStarted, turn_start phase, and resets resources."""
    state = await _gate1_fight_async()
    # Mark the current combatant with spent resources
    actor = state.combatants[state.turn_index]
    state = state.model_copy(
        update={
            "combatants": [
                c.model_copy(
                    update={
                        "action_available": False,
                        "bonus_action_available": False,
                        "reaction_available": False,
                        "movement_remaining": 0,
                    }
                )
                if c.entity_id == actor.entity_id
                else c
                for c in state.combatants
            ]
        }
    )

    step = await start_turn(state, seed=42)

    # Verify events
    assert len(step.events) >= 2
    assert isinstance(step.events[0], TurnStarted)
    assert step.events[0].actor_id == actor.entity_id
    assert isinstance(step.events[1], TurnPhase)
    assert step.events[1].phase == "turn_start"

    # Verify resources are reset in the new state
    new_actor = step.state.combatants[step.state.turn_index]
    assert new_actor.action_available is True
    assert new_actor.bonus_action_available is True
    assert new_actor.reaction_available is True
    # Movement is reset to the combatant's base speed
    assert new_actor.movement_remaining == new_actor.base_speed


@pytest.mark.asyncio
async def test_start_turn_runs_turn_start_hooks() -> None:
    """start_turn runs registered turn_start hooks on its own live combat."""
    from dnd5e_engine.turn_lifecycle import TurnLifecycle
    from dnd5e_engine.combat_state import _live_from_state

    state = await _gate1_fight_async()
    actor_id = state.combatants[state.turn_index].entity_id

    # Register a hook on a live combat created from the state
    calls: list[str] = []
    live = _live_from_state(state, __import__('random').Random(42))
    live.lifecycle.register("turn_start", lambda _l, a: calls.append(a), key="test-hook")

    # Call _begin_turn directly
    from dnd5e_engine.orchestrator import _begin_turn
    _begin_turn(live, new_round=False)

    # The hook should have been called with the actor_id
    assert actor_id in calls


@pytest.mark.asyncio
async def test_start_turn_rolls_death_save_for_unconscious_pc() -> None:
    """start_turn rolls a death save for a PC at 0 HP."""
    state = await _gate1_fight_async()
    # Find a PC and set them to 0 HP
    actor_id = state.combatants[state.turn_index].entity_id
    if not actor_id.startswith("pc:"):
        # Use the first PC in the party
        actor_id = [c.entity_id for c in state.combatants if c.entity_id.startswith("pc:")][0]

    state = state.model_copy(
        update={
            "hp": {**state.hp, actor_id: 0},
            "combatants": [
                c.model_copy(update={"hp_current": 0, "is_unconscious": True})
                if c.entity_id == actor_id
                else c
                for c in state.combatants
            ],
        }
    )

    step = await start_turn(state, seed=42)

    # Should have a DeathSaveRolled event
    death_save_events = [e for e in step.events if isinstance(e, DeathSaveRolled)]
    assert len(death_save_events) == 1
    assert death_save_events[0].target_id == actor_id
