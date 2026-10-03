"""Opportunity attacks roll through the shared d20 primitive.

``_fire_opportunity_attacks_on_step`` rolls every opportunity attack through
``activities/d20.py::roll_d20_test``, so SRD 5.2 Exhaustion's flat D20 Test
penalty (``rules/conditions.py::d20_test_penalty``), the Prone/Grappled
condition rows (``conditions_grant_advantage_on_attack``) and the Dodge
action's disadvantage (``_dodge_benefit_active``) all reach it, while a
condition-free attack still draws exactly ONE d20 (the documented "normal
mode is one draw" invariant).

Layout: the hero at 1,0 and the goblin at 2,0, 5 ft apart on a 10x10 grid.
A step to 0,0 (the hero's) or 3,0 (the goblin's) leaves the other's reach.
"""

from __future__ import annotations

import random

from dnd5e_engine import PlayerIntent
from dnd5e_engine.events import AttackRolled, DamageApplied
from dnd5e_engine.orchestrator import (
    _fire_opportunity_attacks_on_step,
    _get_live,
    start_combat,
    submit_player_intent,
)
from dnd5e_engine.specs import EncounterMemberSpec, PartyMemberSpec
from dnd5e_engine.types.conditions import ActiveCondition
from tests.e2e.harness import cell, events_of, grid_scene, run_async

HERO_CELL = cell(1, 0)
GOBLIN_CELL = cell(2, 0)


def _set_condition(live, entity_id: str, condition: str, **kwargs: object) -> None:
    """Force ``condition`` onto ``entity_id`` via a direct initiative-list
    write — the same test-only pattern ``test_dodge_help_hide.py`` uses
    (no combat-turn action needed to arrange the scenario)."""
    for idx, c in enumerate(live.initiative):
        if c.entity_id == entity_id:
            live.initiative[idx] = c.model_copy(
                update={
                    "conditions": [
                        ActiveCondition(
                            condition=condition,
                            source_entity_id="implied:scenario",
                            scope="combat",
                            **kwargs,
                        )
                    ]
                }
            )
            return
    raise AssertionError(f"{entity_id} not found in initiative")


def _set_dodging(live, entity_id: str) -> None:
    for idx, c in enumerate(live.initiative):
        if c.entity_id == entity_id:
            live.initiative[idx] = c.model_copy(update={"dodging": True})
            return
    raise AssertionError(f"{entity_id} not found in initiative")


async def _start(session_id: str, *, rng_seed: int = 1, hero_attack_bonus: int | None = None):
    """The hero (``char:hero``, initiative 20) beside a goblin warrior
    (``mon:goblin``). ``hero_attack_bonus`` pins the hero's to-hit."""
    pinned = {} if hero_attack_bonus is None else {"attack_bonus": hero_attack_bonus}
    return await start_combat(
        session_id=session_id,
        party=[
            PartyMemberSpec(
                entity_id="char:hero",
                name="Hero",
                initiative=20,
                hp_current=20,
                hp_max=20,
                ac=10,
                base_speed=30,
                zone_id=HERO_CELL,
                **pinned,
            )
        ],
        encounter=[
            EncounterMemberSpec(
                entity_id="mon:goblin",
                entity_type="Monster",
                name="Goblin",
                initiative=1,
                hp_current=7,
                hp_max=7,
                ac=13,
                monster_template_slug="goblin-warrior",
                zone_id=GOBLIN_CELL,
            )
        ],
        grid_scene=grid_scene(),
        rng_seed=rng_seed,
    )


def test_prone_reactor_aoo_rolls_disadvantage_with_condition_attacker_source():
    """(a) SRD 5.2 Prone: "You have Disadvantage on attack rolls." A PRONE
    PC reactor's AoO against a monster mover rolls with disadvantage and
    names ``condition:attacker`` among the sources."""

    async def _run():
        start = await _start("t9-a-prone-reactor", hero_attack_bonus=0)
        live = _get_live(start.handle)
        _set_condition(live, "char:hero", "prone")
        _fire_opportunity_attacks_on_step(
            live, mover_id="mon:goblin", from_cell=GOBLIN_CELL, to_cell=cell(3, 0)
        )
        return live

    live = run_async(_run())
    rolled = next(e for e in events_of(live, AttackRolled) if e.attacker_id == "char:hero")
    assert rolled.advantage == "disadvantage"
    assert "condition:attacker" in rolled.sources


def test_dodging_mover_imposes_disadvantage_on_the_aoo_against_it():
    """(b) SRD 5.2 Dodge: "any attack roll made against you has
    Disadvantage." A DODGING PC mover imposes disadvantage on the
    monster-reactor AoO fired against it, sourced ``"dodge"``."""

    async def _run():
        start = await _start("t9-b-dodging-mover")
        live = _get_live(start.handle)
        _set_dodging(live, "char:hero")
        _fire_opportunity_attacks_on_step(
            live, mover_id="char:hero", from_cell=HERO_CELL, to_cell=cell(0, 0)
        )
        return live

    live = run_async(_run())
    rolled = next(e for e in events_of(live, AttackRolled) if e.target_id == "char:hero")
    assert rolled.advantage == "disadvantage"
    assert "dodge" in rolled.sources


def test_exhausted_reactor_d20_test_penalty_reaches_the_aoo_total():
    """(c) SRD 5.2 Exhaustion: "the roll is reduced by 2 times your
    Exhaustion level" on EVERY D20 Test, opportunity attacks included. An
    Exhaustion-1 PC reactor's AoO modifier reflects the -2 penalty."""

    async def _run():
        start = await _start("t9-c-exhausted-reactor", hero_attack_bonus=0)
        live = _get_live(start.handle)
        _set_condition(live, "char:hero", "exhaustion", exhaustion_level=1)
        _fire_opportunity_attacks_on_step(
            live, mover_id="mon:goblin", from_cell=GOBLIN_CELL, to_cell=cell(3, 0)
        )
        return live

    live = run_async(_run())
    reactor = next(c for c in live.initiative if c.entity_id == "char:hero")
    rolled = next(e for e in events_of(live, AttackRolled) if e.attacker_id == "char:hero")
    assert rolled.modifier == reactor.attack_bonus - 2


def test_condition_free_aoo_determinism_pin_matches_pre_change_natural():
    """(d) Determinism pin: a condition-free AoO at ``rng_seed=1`` still
    draws exactly ONE d20 in normal mode: the first draw of the seeded
    stream, a natural 5 (the goblin's ``attack_bonus`` is 0, so the total is
    5 too). The hero's move from 1,0 to 0,0 leaves the goblin's reach on
    its only step."""

    async def _run():
        start = await _start("t9-d-determinism-pin", rng_seed=1)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="move", target_zone_id=cell(0, 0)),
        )
        return _get_live(start.handle)

    live = run_async(_run())
    rolled = next(
        e
        for e in events_of(live, AttackRolled)
        if e.attacker_id == "mon:goblin" and e.is_opportunity_attack
    )
    assert rolled.advantage == "normal"
    assert rolled.natural == 5
    assert rolled.roll_total == 5


class _NatTwentyRng(random.Random):
    """Deterministic stand-in for the live combat's seeded RNG: every d20
    draw (``randint(1, 20)``) is forced to a natural 20 so the opportunity
    attack always crits; every other draw (weapon damage) returns a fixed
    pip count so damage is always > 0. Swapped in for ``live.rng`` AFTER
    ``start_combat`` (which already consumed the real seeded RNG for
    initiative), mirroring ``test_action_economy_attacks.py``'s
    ``_ForcedRng`` idiom."""

    def randint(self, a: int, b: int) -> int:
        if (a, b) == (1, 20):
            return 20
        return 4


def test_opportunity_attack_nat_20_damage_is_attributed_and_flagged_crit():
    """F2 — a forced natural-20 opportunity attack's ``DamageApplied``
    threads ``is_crit`` and ``source_id``. The hero carries no weapon, so its
    opportunity attack rolls the legacy ``attack_bonus`` / ``damage_dice``
    swing and is attributed that path's synthesized id."""

    async def _run():
        start = await _start("t9-e-crit-oa-attribution", hero_attack_bonus=0)
        live = _get_live(start.handle)
        live.rng = _NatTwentyRng()
        _fire_opportunity_attacks_on_step(
            live, mover_id="mon:goblin", from_cell=GOBLIN_CELL, to_cell=cell(3, 0)
        )
        return live

    live = run_async(_run())
    rolled = next(e for e in events_of(live, AttackRolled) if e.attacker_id == "char:hero")
    assert rolled.natural == 20
    assert rolled.is_crit is True
    damaged = next(e for e in events_of(live, DamageApplied) if e.target_id == "mon:goblin")
    assert damaged.is_crit is True
    assert damaged.source_id == "synth:legacy-swing"
