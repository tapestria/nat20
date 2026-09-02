"""C14 Task 9 — opportunity attacks route through the shared d20 primitive.

Prior to this change, ``orchestrator.py``'s two opportunity-attack fire
sites (``_fire_pc_opportunity_attacks_on_move`` /
``_fire_monster_opportunity_attacks_on_move``) rolled a raw
``live.rng.randint(1, 20)`` and hard-coded ``advantage="normal"`` on the
emitted ``AttackRolled`` — bypassing ``activities/d20.py::roll_d20_test``
entirely. That meant SRD 5.2 Exhaustion's flat D20 Test penalty
(``rules/conditions.py::d20_test_penalty``), Prone/Grappled condition rows
(``conditions_grant_advantage_on_attack``), and the Dodge action's
disadvantage (``_dodge_benefit_active``) never reached an opportunity
attack roll — only the regular Attack activity path saw them.

These tests pin the fixed behavior: both fire sites now assemble the same
typed ``AdvantageSources`` the regular attack path uses and roll through
``roll_d20_test``, while a condition-free AoO at a fixed seed still draws
exactly ONE d20 (the documented "normal mode is one draw" invariant), so
every pre-existing seeded AoO scenario is untouched.
"""

from __future__ import annotations

import random

from dnd5e_engine import PlayerIntent
from dnd5e_engine.events import AttackRolled, DamageApplied
from dnd5e_engine.orchestrator import (
    _fire_monster_opportunity_attacks_on_move,
    _fire_pc_opportunity_attacks_on_move,
    _get_live,
    start_combat,
    submit_player_intent,
)
from dnd5e_engine.specs import EncounterMemberSpec, PartyMemberSpec, SceneTopology, ZoneEdge
from dnd5e_engine.types.conditions import ActiveCondition
from tests.e2e.harness import events_of, run_async


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


async def _start_pc_reactor_combat(session_id: str, *, rng_seed: int = 1):
    """A PC reactor (``char:hero``) and a monster mover (``mon:goblin``),
    both starting in ``zone:a`` with an edge to ``zone:b`` — the setup the
    shipped PC-reactor AoO fire site expects."""
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
                attack_bonus=0,
                base_speed=30,
                zone_id="zone:a",
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
                zone_id="zone:a",
            )
        ],
        scene_zones=SceneTopology(
            zones=["zone:a", "zone:b"],
            edges=[ZoneEdge(a="zone:a", b="zone:b", distance_ft=10)],
        ),
        rng_seed=rng_seed,
    )


async def _start_monster_reactor_combat(session_id: str, *, rng_seed: int = 1):
    """Mirror of ``_start_pc_reactor_combat`` for the monster-reactor /
    PC-mover direction — the exact C06-S05 shape."""
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
                zone_id="zone:a",
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
                zone_id="zone:a",
            )
        ],
        scene_zones=SceneTopology(
            zones=["zone:a", "zone:b"],
            edges=[ZoneEdge(a="zone:a", b="zone:b", distance_ft=10)],
        ),
        rng_seed=rng_seed,
    )


def test_prone_reactor_aoo_rolls_disadvantage_with_condition_attacker_source():
    """(a) SRD 5.2 Prone: "You have Disadvantage on attack rolls." A PRONE
    PC reactor's AoO against a fleeing monster mover rolls with
    disadvantage and names ``condition:attacker`` among the sources."""

    async def _run():
        start = await _start_pc_reactor_combat("t9-a-prone-reactor")
        live = _get_live(start.handle)
        _set_condition(live, "char:hero", "prone")
        _fire_pc_opportunity_attacks_on_move(
            live, mover_id="mon:goblin", from_zone="zone:a", to_zone="zone:b"
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
        start = await _start_monster_reactor_combat("t9-b-dodging-mover")
        live = _get_live(start.handle)
        _set_dodging(live, "char:hero")
        _fire_monster_opportunity_attacks_on_move(
            live, mover_id="char:hero", from_zone="zone:a", to_zone="zone:b"
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
        start = await _start_pc_reactor_combat("t9-c-exhausted-reactor")
        live = _get_live(start.handle)
        _set_condition(live, "char:hero", "exhaustion", exhaustion_level=1)
        _fire_pc_opportunity_attacks_on_move(
            live, mover_id="mon:goblin", from_zone="zone:a", to_zone="zone:b"
        )
        return live

    live = run_async(_run())
    reactor = next(c for c in live.initiative if c.entity_id == "char:hero")
    rolled = next(e for e in events_of(live, AttackRolled) if e.attacker_id == "char:hero")
    assert rolled.modifier == reactor.attack_bonus - 2


def test_condition_free_aoo_determinism_pin_matches_pre_change_natural():
    """(d) Determinism pin: a condition-free AoO at ``rng_seed=1`` still
    draws exactly ONE d20 in normal mode, so the KEPT die is unchanged
    from the pre-``roll_d20_test`` behavior.

    Expectation captured by running this exact scenario (identical to
    ``tests/e2e/test_c06_reactions.py::test_c06_s05_...``) against the
    orchestrator at HEAD (``dc3948f``, before this task's change): the raw
    ``live.rng.randint(1, 20)`` draw at that point in the seeded stream was
    ``5`` (goblin ``attack_bonus == 0``, so ``roll_total`` was also ``5``).
    """

    async def _run():
        start = await _start_monster_reactor_combat("t9-d-determinism-pin", rng_seed=1)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="move", target_zone_id="zone:b"),
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
    """F2 — a forced natural-20 opportunity attack's ``DamageApplied`` now
    threads ``is_crit`` and ``source_id`` (previously both silently
    defaulted, so a crit OA looked identical to a normal-hit OA on the
    damage event and the damage was unattributed). An OA always resolves
    through the reactor's legacy ``attack_bonus``/``damage_dice`` fields
    (never a typed weapon/activity — see
    ``orchestrator._synthesize_attack_from_legacy_fields``), so it is
    attributed the same synthesized id that path uses."""

    async def _run():
        start = await _start_pc_reactor_combat("t9-e-crit-oa-attribution")
        live = _get_live(start.handle)
        live.rng = _NatTwentyRng()
        _fire_pc_opportunity_attacks_on_move(
            live, mover_id="mon:goblin", from_zone="zone:a", to_zone="zone:b"
        )
        return live

    live = run_async(_run())
    rolled = next(e for e in events_of(live, AttackRolled) if e.attacker_id == "char:hero")
    assert rolled.natural == 20
    assert rolled.is_crit is True
    damaged = next(e for e in events_of(live, DamageApplied) if e.target_id == "mon:goblin")
    assert damaged.is_crit is True
    assert damaged.source_id == "synth:legacy-swing"
