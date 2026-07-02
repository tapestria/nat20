"""C10 — Monster behavior.

Transcribed from specs/e2e-scenario-catalog.md, Cluster 10.
"""

from __future__ import annotations

from dnd5e_engine.events import ActorMoved, AttackRolled
from dnd5e_engine.orchestrator import _get_live, advance_monster_turn, start_combat
from dnd5e_engine.specs import EncounterMemberSpec, PartyMemberSpec, SceneTopology, ZoneEdge
from tests.e2e.harness import events_of, run_async, xfail_cluster


@xfail_cluster(10, "Monster behavior")
def test_c10_s01_fleeing_monster_never_actually_retreats():
    """C10-S01: A low-HP AGGRESSIVE monster stops attacking below the SRD
    flee threshold but never actually retreats — zero movement, it simply
    stands still.

    Monster AI is DM-adjudicated behavior, not codified SRD rules text —
    this is engine/Foundry-parity plumbing (the legacy `monster_ai` gambit
    heuristic this engine ports); engine:
    packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py
    (`_monster_is_fleeing`, lines 415-430 — "Faithful port of
    `monster_ai.select_monster_action` (monster_ai.py:163-171): an
    AGGRESSIVE monster passes below 10% HP..."; `advance_monster_turn`,
    lines 3442+ — `skip_to_record_pass = ... or
    _monster_is_fleeing(current)`; when `True`, the movement-toward-target
    block never runs either — the fleeing monster's entire turn collapses
    to a bare `IntentSubmitted(intent_type="pass")` with no movement of any
    kind) and packages/dnd5e-engine/src/dnd5e_engine/rules/gambits.py
    (`select_action` — the OLD, richer per-profile gambit picker that DOES
    return a distinct `action_type="flee"`, but is dead code — never called
    from `advance_monster_turn`'s live path).
    """

    async def _run():
        start = await start_combat(
            session_id="e2e-c10-s01",
            party=[
                PartyMemberSpec(
                    entity_id="char:hero",
                    name="Hero",
                    initiative=1,
                    hp_current=30,
                    hp_max=30,
                    ac=15,
                    attack_bonus=5,
                    zone_id="zone:pc",
                )
            ],
            encounter=[
                EncounterMemberSpec(
                    entity_id="mon:goblin",
                    entity_type="Monster",
                    name="Goblin",
                    initiative=20,
                    hp_current=1,
                    hp_max=20,
                    ac=13,
                    zone_id="zone:foe",
                    monster_template_slug="goblin-warrior",
                    base_speed=30,
                    behavior_profile="AGGRESSIVE",
                )
            ],
            scene_zones=SceneTopology(
                zones=["zone:retreat", "zone:foe", "zone:pc"],
                edges=[
                    ZoneEdge(a="zone:retreat", b="zone:foe", distance_ft=15),
                    ZoneEdge(a="zone:foe", b="zone:pc", distance_ft=15),
                ],
            ),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        await advance_monster_turn(start.handle)
        return live

    live = run_async(_run())
    moves = [e for e in events_of(live, ActorMoved) if e.actor_id == "mon:goblin"]
    assert moves, "a fleeing monster with a movement budget should retreat"
    total_distance = sum(e.distance_ft for e in moves)
    assert 0 < total_distance <= 30
    assert live.actor_zone["mon:goblin"] == "zone:retreat"


@xfail_cluster(10, "Monster behavior")
def test_c10_s02_ranged_profile_multiattack_fallback_ignores_own_longbow():
    """C10-S02: A RANGED-profile monster's multiattack fallback always
    picks the first-listed (melee) sibling by dict order, ignoring its own
    longbow and the target's actual distance.

    The SRD-grounded fact this scenario pins is the Scout's own stat
    block: packages/dnd5e-srd-data/src/dnd5e_srd_data/canonical/monsters/scout.json
    (`actions`: `shortsword` — melee, `range.value="5"`; `longbow` —
    ranged, `range.value="150"`; `multiattack` — description carries no
    rendered `[[/item]]{label}` tokens); engine:
    packages/dnd5e-engine/src/dnd5e_engine/activities/monster_actions.py
    (`select_typed_monster_action` — always returns `multiattack` first
    when present, with zero profile/range awareness;
    `expand_action_to_activities` — falls to the documented fallback:
    "repeat the first attack sibling's first offensive activity `count`
    times" — `_attack_siblings` preserves `Monster.actions` list order, so
    `siblings[0]` is `shortsword` regardless of range, profile, or
    tactical fit) versus
    packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py
    (`_monster_attack_range_ft` keys off the FIRST resolved activity — here,
    `shortsword`'s `range.value="5"` — so the movement gate treats the
    WHOLE multiattack as melee-range, even though the monster's own
    (ignored) longbow is already in range and needs no movement at all).
    """

    async def _run():
        start = await start_combat(
            session_id="e2e-c10-s02",
            party=[
                PartyMemberSpec(
                    entity_id="char:hero",
                    name="Hero",
                    initiative=1,
                    hp_current=30,
                    hp_max=30,
                    ac=15,
                    attack_bonus=5,
                    zone_id="zone:pc",
                )
            ],
            encounter=[
                EncounterMemberSpec(
                    entity_id="mon:scout",
                    entity_type="Monster",
                    name="Scout",
                    initiative=20,
                    hp_current=16,
                    hp_max=16,
                    ac=13,
                    zone_id="zone:foe",
                    monster_template_slug="scout",
                    base_speed=30,
                    behavior_profile="RANGED",
                )
            ],
            scene_zones=SceneTopology(
                zones=["zone:foe", "zone:pc"],
                edges=[ZoneEdge(a="zone:foe", b="zone:pc", distance_ft=100)],
            ),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        await advance_monster_turn(start.handle)
        return live

    live = run_async(_run())
    attacks = [e for e in events_of(live, AttackRolled) if e.attacker_id == "mon:scout"]
    assert attacks, "the scout should fire its longbow — already within its 150 ft range"
    moves = [e for e in events_of(live, ActorMoved) if e.actor_id == "mon:scout"]
    assert not moves, "no repositioning was ever needed"
