"""A host chooses the creature a monster attacks.

``advance_monster_turn(handle, target_id=...)`` names the creature the acting
monster attacks this turn, or targets with its stat-block cast; ``None``
keeps the built-in lowest-HP pick. The id must be in the monster's own target
pool: an enemy in the initiative order with more than 0 Hit Points, and not
the monster's charmer (SRD 5.2 Charmed: "You can't attack the charmer or
target the charmer with damaging abilities or magical effects"). Any other id
is refused with ``target_invalid`` before the turn starts, so nothing is
rolled, spent or emitted. SRD 5.2 Summon Dragon: "If you don't issue any [command],
it takes the Dodge action", so a summon's turn takes no target. An area
keeps the engine's aim.
"""

from __future__ import annotations

import asyncio
import copy
import random
from typing import Any

import pytest

from dnd5e_engine import CombatHandle
from dnd5e_engine.events import (
    ActorMoved,
    AreaTargeted,
    AttackRolled,
    DashTaken,
    Death,
    IntentSubmitted,
    LegendaryActionUsed,
    SaveRolled,
)
from dnd5e_engine.orchestrator import (
    IntentRejectedError,
    _current_actor,
    _LiveCombat,
    advance_monster_turn,
)
from dnd5e_engine.spatial import cell_id
from dnd5e_engine.testing import rng_factory
from dnd5e_engine.types.conditions import ActiveCondition
from tests.c21_support import (
    act,
    anchor_effect,
    combatant,
    events,
    foe,
    pc,
    seat_summon,
    start,
)

CHARMER = "char:00000000cafe"  # a condition source takes a 12-hex-digit id


class _D20Always20(random.Random):
    def randint(self, a: int, b: int) -> int:
        return 20 if (a, b) == (1, 20) else super().randint(a, b)


def _advance(handle: CombatHandle, **kwargs: Any) -> None:
    asyncio.run(advance_monster_turn(handle, **kwargs))


def _refused(handle: CombatHandle, **kwargs: Any) -> str:
    with pytest.raises(IntentRejectedError) as excinfo:
        _advance(handle, **kwargs)
    return excinfo.value.reason


def _state(live: _LiveCombat) -> tuple[object, ...]:
    return (
        len(live.event_log),
        live.rng.getstate(),
        live.current_turn_index,
        copy.deepcopy(live.monster_action_uses_by_entity),
        [c.model_dump() for c in live.initiative],
    )


def _dragon(slug: str, col: int, row: int, **fields: Any) -> Any:
    base = {"monster_template_slug": slug, "hp_current": 200, "hp_max": 200}
    return foe(zone_id=cell_id(col, row), **(base | fields))


def test_the_named_target_is_attacked_over_the_lowest_hp_one() -> None:
    handle, live = start(
        [pc(), pc("char:low", initiative=19, hp_current=10, zone_id=cell_id(2, 0))], seed=1
    )
    act(handle, "char:hero", intent_type="pass")
    act(handle, "char:low", intent_type="pass")
    _advance(handle, target_id="char:hero")
    [intent] = [e for e in events(live, IntentSubmitted) if e.actor_id == "mon:foe"]
    assert (intent.intent_type, intent.target_id) == ("attack", "char:hero")
    assert [a.target_id for a in events(live, AttackRolled)] == ["char:hero"]


def _refusal_scene() -> tuple[CombatHandle, _LiveCombat]:
    """The dragon's turn, its Fire Breath spent (a turn start would roll its
    recharge); the hero (two attacks per Attack action) has killed a
    party-side ally and knocked out ``char:ko``; ``char:down`` lies at 0 Hit
    Points; the dragon is charmed by ``CHARMER``."""
    with rng_factory(_D20Always20):
        handle, live = start(
            [
                pc(class_slug="fighter", character_level=5),
                pc("char:ko", initiative=5, hp_current=1, zone_id=cell_id(1, 0)),
                pc("char:down", initiative=3, hp_current=0, zone_id=cell_id(0, 2)),
                pc(CHARMER, initiative=2, zone_id=cell_id(0, 3)),
            ],
            seed=2,
            encounter=[
                _dragon("young-red-dragon", 4, 4, initiative=19),
                foe(entity_id="mon:foe-2", initiative=1, zone_id=cell_id(9, 9)),
                foe(
                    entity_id="npc:ally",
                    entity_type="NPC",
                    side="party",
                    initiative=4,
                    hp_current=1,
                    hp_max=1,
                    zone_id=cell_id(1, 1),
                ),
            ],
        )
    act(handle, "char:hero", intent_type="attack", weapon_id="longsword", target_id="npc:ally")
    assert [d.target_id for d in events(live, Death)] == ["npc:ally"]
    act(
        handle,
        "char:hero",
        intent_type="attack",
        weapon_id="longsword",
        target_id="char:ko",
        knock_out=True,
    )
    assert live.knocked_out_ids == {"char:ko"}
    act(handle, "char:hero", intent_type="pass")
    assert _current_actor(live).entity_id == "mon:foe"
    live.monster_action_uses_by_entity["mon:foe"]["fire-breath"].recharge_spent = True
    combatant(live, "mon:foe").conditions.append(
        ActiveCondition(condition="charmed", source_entity_id=CHARMER, scope="combat")
    )
    live.active_conditions.setdefault("mon:foe", set()).add("charmed")
    return handle, live


@pytest.mark.parametrize(
    "target_id",
    [
        "char:ghost",  # not in the combat
        "mon:foe-2",  # the actor's own ally
        "npc:ally",  # dead
        "char:down",  # a character at 0 Hit Points
        "char:ko",  # knocked out
        CHARMER,  # the actor's charmer
    ],
)
def test_an_illegal_target_is_refused_with_nothing_spent(target_id: str) -> None:
    handle, live = _refusal_scene()
    before = _state(live)
    assert _refused(handle, target_id=target_id) == "target_invalid"
    assert _state(live) == before


def test_the_refusal_scene_is_otherwise_a_live_turn() -> None:
    """Without the bad id, the same call rolls the recharge and acts."""
    handle, live = _refusal_scene()
    before = _state(live)
    _advance(handle, target_id="char:hero")
    assert _state(live) != before
    assert live.rng.getstate() != before[1]


def test_any_target_on_a_summons_turn_is_refused() -> None:
    handle, live = start([pc()], seed=3, active_effects=[anchor_effect("char:hero")])
    spirit = seat_summon(live, "char:hero", zone_id=cell_id(0, 1))
    act(handle, "char:hero", intent_type="pass")
    assert _current_actor(live).entity_id == spirit
    before = _state(live)
    assert _refused(handle, target_id="mon:foe") == "target_invalid"
    assert _state(live) == before


def test_a_characters_turn_is_refused_as_before() -> None:
    handle, _ = start([pc()], seed=4)
    assert _refused(handle, target_id="char:hero") == "not_actor_turn"


@pytest.mark.parametrize("why", ["fleeing", "paralyzed"])
def test_an_actor_that_cannot_act_validates_the_id_then_passes(why: str) -> None:
    fields = {"hp_current": 1} if why == "fleeing" else {}
    handle, live = start([pc()], seed=5, encounter=[foe(**fields)])
    if why == "paralyzed":
        combatant(live, "mon:foe").conditions.append(
            ActiveCondition(condition="paralyzed", source_entity_id="implied:test", scope="combat")
        )
    act(handle, "char:hero", intent_type="pass")
    before = _state(live)
    assert _refused(handle, target_id="char:ghost") == "target_invalid"
    assert _state(live) == before
    _advance(handle, target_id="char:hero")
    [intent] = [e for e in events(live, IntentSubmitted) if e.actor_id == "mon:foe"]
    assert intent.intent_type == "pass"
    assert not [a for a in events(live, AttackRolled) if a.attacker_id == "mon:foe"]


def test_an_out_of_reach_target_is_walked_to_never_swapped() -> None:
    far = pc("char:far", initiative=19, hp_current=60, hp_max=60, zone_id=cell_id(9, 0))
    handle, live = start([pc(), far], seed=6)
    act(handle, "char:hero", intent_type="pass")
    act(handle, "char:far", intent_type="pass")
    _advance(handle, target_id="char:far")
    [intent] = [e for e in events(live, IntentSubmitted) if e.actor_id == "mon:foe"]
    assert intent.target_id == "char:far"
    assert intent.intent_type == "dash"
    assert [e for e in events(live, DashTaken) if e.actor_id == "mon:foe"]
    assert [e for e in events(live, ActorMoved) if e.actor_id == "mon:foe"]
    assert not [a for a in events(live, AttackRolled) if a.attacker_id == "mon:foe"]
    # It closed on the named creature rather than swinging at the adjacent hero.
    col, _ = (int(n) for n in live.actor_zone["mon:foe"].split(","))
    assert col > 1


def test_an_area_keeps_the_engines_aim() -> None:
    handle, live = start(
        [
            pc("char:a", zone_id=cell_id(5, 7)),
            pc("char:b", initiative=19, zone_id=cell_id(5, 8)),
            pc("char:c", initiative=18, zone_id=cell_id(5, 4)),
        ],
        seed=1,
        encounter=[_dragon("adult-red-dragon", 5, 5, initiative=25)],
    )
    _advance(handle, target_id="char:c")
    [area] = [e for e in live.event_log if isinstance(e, AreaTargeted)]
    assert area.source_id == "fire-breath"
    assert set(area.affected_ids) == {"char:a", "char:b"}
    assert "char:c" not in {s.target_id for s in events(live, SaveRolled)}


def _legendary_scene() -> tuple[CombatHandle, _LiveCombat]:
    handle, live = start(
        [
            pc(initiative=25, hp_current=60, hp_max=60),
            pc("char:low", initiative=24, hp_current=20, zone_id=cell_id(0, 1)),
        ],
        seed=4,
        encounter=[_dragon("adult-red-dragon", 3, 0, initiative=10, hp_current=256)],
    )
    act(handle, "char:hero", intent_type="pass")
    return handle, live


def test_a_legendary_action_takes_the_named_target() -> None:
    handle, live = _legendary_scene()
    _advance(handle, legendary=True, target_id="char:hero")
    assert events(live, LegendaryActionUsed)
    targets = {e.target_id for e in events(live, AttackRolled)} | {
        e.target_id for e in events(live, SaveRolled)
    }
    assert targets == {"char:hero"}


def test_an_illegal_legendary_target_is_refused_before_the_action() -> None:
    handle, live = _legendary_scene()
    before = _state(live)
    assert _refused(handle, legendary=True, target_id="char:ghost") == "target_invalid"
    assert _state(live) == before
    assert not events(live, LegendaryActionUsed)
