"""C15 — Attack rules.

Transcribed from specs/e2e-scenario-catalog.md, Cluster 15
(specs/catalog-v2/c15.md). All setups are Grid-only (``GridScene`` +
``cell_id``), mirroring ``tests/e2e/test_c05_spatial.py``.
"""

from __future__ import annotations

import contextlib

from dnd5e_engine import PlayerIntent
from dnd5e_engine.events import AttackFailed, AttackRolled, DamageApplied, Death
from dnd5e_engine.orchestrator import (
    IntentRejectedError,
    _get_live,
    start_combat,
    submit_player_intent,
)
from dnd5e_engine.specs import EncounterMemberSpec, GridScene, PartyMemberSpec
from tests.e2e.harness import cell, events_of, grid_scene, run_async, xfail_cluster


def test_c15_s01_nonproficient_attacker_still_adds_proficiency_bonus():
    """C15-S01: SRD 5.2 — "you must have proficiency with it to add your
    Proficiency Bonus to an attack roll you make with it."
    (packs/_source/content24/chapter-6/equipment.yml, id dWQ2ZTLOuKr3PMAx,
    heading "Weapon Proficiency"). ``PartyMemberSpec`` has no
    ``weapon_proficiencies`` field today (``ConfigDict(extra="forbid")``
    rejects it) and ``build_context.py`` hard-codes
    ``is_proficient_attack=True`` regardless of what a caller declares.
    """

    def _hero_kwargs(nonproficient: bool) -> dict:
        kwargs: dict = dict(
            entity_id="char:hero",
            name="Hero",
            initiative=20,
            hp_current=20,
            hp_max=20,
            strength=16,
            character_level=1,
            zone_id=cell(0, 0),
        )
        if nonproficient:
            # API delta (C15): weapon_proficiencies does not exist today.
            kwargs["weapon_proficiencies"] = ()
        return kwargs

    def _run(nonproficient: bool):
        async def _inner():
            start = await start_combat(
                session_id="e2e-c15-s01",
                party=[PartyMemberSpec(**_hero_kwargs(nonproficient))],
                encounter=[
                    EncounterMemberSpec(
                        entity_id="mon:foe",
                        entity_type="Monster",
                        name="Foe",
                        initiative=1,
                        hp_current=500,
                        hp_max=500,
                        ac=1,
                        zone_id=cell(0, 1),
                    )
                ],
                scene_zones=None,
                grid_scene=grid_scene(),
                rng_seed=1,
            )
            live = _get_live(start.handle)
            await submit_player_intent(
                start.handle,
                actor_id="char:hero",
                intent=PlayerIntent(
                    intent_type="attack", weapon_id="longsword", target_id="mon:foe"
                ),
            )
            return live

        return run_async(_inner())

    live_a = _run(False)
    live_b = _run(True)

    base_total = next(
        e for e in events_of(live_a, AttackRolled) if e.target_id == "mon:foe"
    ).roll_total
    nonprof_total = next(
        e for e in events_of(live_b, AttackRolled) if e.target_id == "mon:foe"
    ).roll_total

    # Proficiency Bonus at level 1 is +2, omitted entirely (never a penalty).
    assert base_total - nonprof_total == 2


@xfail_cluster(15, "attack rules")
def test_c15_s02_ranged_attack_disadvantaged_by_adjacent_hostile():
    """C15-S02: SRD 5.2 (Ranged Attacks in Close Combat) — "you have
    Disadvantage on the roll if you are within 5 feet of an enemy who can
    see you and doesn't have the Incapacitated condition."
    (packs/_source/content24/appendices/appendix-d-rule-references.yml,
    id qEZvxW0NM7ixSQP5). ``activities/attack.py::resolve_attack``
    hard-codes ``mode: AdvantageMode = "normal"`` and never queries
    ``spatial.py`` for enemy adjacency.
    """

    def _party():
        return [
            PartyMemberSpec(
                entity_id="char:hero",
                name="Hero",
                initiative=20,
                hp_current=20,
                hp_max=20,
                dexterity=16,
                zone_id=cell(0, 0),
            )
        ]

    def _far_foe():
        return EncounterMemberSpec(
            entity_id="mon:far",
            entity_type="Monster",
            name="Far",
            initiative=1,
            hp_current=100,
            hp_max=100,
            ac=15,
            zone_id=cell(4, 0),
        )

    def _near_foe():
        return EncounterMemberSpec(
            entity_id="mon:near",
            entity_type="Monster",
            name="Near",
            initiative=2,
            hp_current=10,
            hp_max=10,
            ac=15,
            zone_id=cell(1, 0),
        )

    async def _run_a():
        start = await start_combat(
            session_id="e2e-c15-s02-a",
            party=_party(),
            encounter=[_far_foe()],
            scene_zones=None,
            grid_scene=grid_scene(),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="attack", weapon_id="longbow", target_id="mon:far"),
        )
        return live

    async def _run_b():
        start = await start_combat(
            session_id="e2e-c15-s02-b",
            party=_party(),
            encounter=[_far_foe(), _near_foe()],
            scene_zones=None,
            grid_scene=grid_scene(),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="attack", weapon_id="longbow", target_id="mon:far"),
        )
        return live

    live_a = run_async(_run_a())
    live_b = run_async(_run_b())

    rolled_a = next(e for e in events_of(live_a, AttackRolled) if e.target_id == "mon:far")
    rolled_b = next(e for e in events_of(live_b, AttackRolled) if e.target_id == "mon:far")

    assert rolled_a.advantage == "normal"
    assert rolled_b.advantage == "disadvantage"
    assert rolled_b.roll_total <= rolled_a.roll_total


@xfail_cluster(15, "attack rules")
def test_c15_s03_disadvantage_tier_between_normal_and_long_range():
    """C15-S03: SRD 5.2 (Range) — "Your attack roll has Disadvantage when
    your target is beyond normal range, and you can't attack a target
    beyond long range."
    (packs/_source/content24/appendices/appendix-d-rule-references.yml,
    id HjKXuB8ndjcqOds7). ``_weapon_attack_range_ft`` reads ONLY
    ``weapon.range.value`` for a ranged weapon and never consults
    ``weapon.range.long`` — the whole "disadvantaged but legal" middle
    tier is unreachable, and ``col=40`` (200 ft, within light-crossbow's
    320 ft long range) hard-rejects instead of resolving disadvantaged.
    """

    def _run(col: int):
        async def _inner():
            start = await start_combat(
                session_id="e2e-c15-s03",
                party=[
                    PartyMemberSpec(
                        entity_id="char:hero",
                        name="Hero",
                        initiative=20,
                        hp_current=20,
                        hp_max=20,
                        dexterity=16,
                        zone_id=cell(0, 0),
                    )
                ],
                encounter=[
                    EncounterMemberSpec(
                        entity_id="mon:foe",
                        entity_type="Monster",
                        name="Foe",
                        initiative=1,
                        hp_current=100,
                        hp_max=100,
                        ac=15,
                        zone_id=cell(col, 0),
                    )
                ],
                scene_zones=None,
                grid_scene=GridScene(width=200, height=10),
                rng_seed=1,
            )
            live = _get_live(start.handle)
            await submit_player_intent(
                start.handle,
                actor_id="char:hero",
                intent=PlayerIntent(
                    intent_type="attack", weapon_id="light-crossbow", target_id="mon:foe"
                ),
            )
            return live

        return run_async(_inner())

    live_normal = _run(10)  # 50 ft — within normal range.
    live_middle = _run(40)  # 200 ft — beyond normal, within long: disadvantage tier.
    live_beyond = _run(100)  # 500 ft — beyond long range: hard reject.

    normal_rolled = events_of(live_normal, AttackRolled)
    assert normal_rolled
    assert normal_rolled[0].advantage == "normal"

    middle_rolled = events_of(live_middle, AttackRolled)
    assert middle_rolled, "expected a legal (disadvantaged) attack roll at 200 ft"
    assert middle_rolled[0].advantage == "disadvantage"

    beyond_failed = events_of(live_beyond, AttackFailed)
    assert beyond_failed
    assert beyond_failed[0].reason == "out_of_range"


@xfail_cluster(15, "attack rules")
def test_c15_s04_versatile_grip_and_damage_source_attribution():
    """C15-S04: SRD 5.2 (Versatile) — "The weapon deals that damage when
    used with two hands to make a melee attack."
    (packs/_source/content24/chapter-6/equipment.yml, id 7qSj8lqMAP0FBNKK,
    heading "Versatile"). No field on ``PlayerIntent`` exists to request a
    two-handed grip, and ``DamageApplied`` carries no ``source_id``
    attribution (confirmed: ``hasattr(event, "source_id")`` is ``False``).
    """

    async def _run():
        start = await start_combat(
            session_id="e2e-c15-s04",
            party=[
                PartyMemberSpec(
                    entity_id="char:hero",
                    name="Hero",
                    initiative=20,
                    hp_current=20,
                    hp_max=20,
                    strength=16,
                    zone_id=cell(0, 0),
                )
            ],
            encounter=[
                EncounterMemberSpec(
                    entity_id="mon:foe",
                    entity_type="Monster",
                    name="Foe",
                    initiative=1,
                    hp_current=500,
                    hp_max=500,
                    ac=1,
                    zone_id=cell(0, 1),
                )
            ],
            scene_zones=None,
            grid_scene=grid_scene(),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="attack", weapon_id="longsword", target_id="mon:foe"),
        )
        return live

    live = run_async(_run())
    dmg = next(e for e in events_of(live, DamageApplied) if e.target_id == "mon:foe")
    assert hasattr(dmg, "source_id"), "DamageApplied.source_id is not yet a field (C15 delta)"
    assert dmg.source_id is not None

    # API delta (C15): requesting the two-handed grip has no PlayerIntent
    # field today — this raises before the attack can even resolve.
    two_handed_kwargs = dict(intent_type="attack", weapon_id="longsword", target_id="mon:foe")
    two_handed_kwargs["two_handed"] = True
    PlayerIntent(**two_handed_kwargs)


@xfail_cluster(15, "attack rules")
def test_c15_s05_loading_weapon_second_shot_rejected_for_the_right_reason():
    """C15-S05: SRD 5.2 (Loading) — "You can fire only one piece of
    ammunition from a Loading weapon when you use an action, a Bonus
    Action, or a Reaction to fire it, regardless of the number of attacks
    you can normally make."
    (packs/_source/content24/chapter-6/equipment.yml, id 7qSj8lqMAP0FBNKK,
    heading "Loading"). No Extra Attack economy exists to cap yet, so a
    second same-turn attack fails for the WRONG reason today
    (``IntentRejectedError("not_actor_turn")``, because the turn already
    auto-ended) instead of resolving through the pre-resolution reject
    path and emitting a Loading-specific ``AttackFailed(reason=
    "weapon_already_fired")`` event — the same event-based surface as the
    sibling ``out_of_range``/``target_invalid``/``no_action_economy``
    rejects (``orchestrator.py:4478-4540``), per ``specs/catalog-v2/
    API-DELTAS.md``'s ``AttackFailed.reason="weapon_already_fired"``
    entry (NOT a new ``IntentRejectedError`` reason — that Literal stays
    closed).
    """

    async def _run():
        start = await start_combat(
            session_id="e2e-c15-s05",
            party=[
                PartyMemberSpec(
                    entity_id="char:hero",
                    name="Hero",
                    initiative=20,
                    hp_current=20,
                    hp_max=20,
                    dexterity=16,
                    zone_id=cell(0, 0),
                )
            ],
            encounter=[
                EncounterMemberSpec(
                    entity_id="mon:foe",
                    entity_type="Monster",
                    name="Foe",
                    initiative=1,
                    hp_current=500,
                    hp_max=500,
                    ac=1,
                    zone_id=cell(1, 0),
                )
            ],
            scene_zones=None,
            grid_scene=grid_scene(),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(
                intent_type="attack", weapon_id="light-crossbow", target_id="mon:foe"
            ),
        )
        # Today this raises IntentRejectedError("not_actor_turn") instead of
        # resolving through the pre-resolution reject path — suppress so the
        # event-based assertions below (which pin the SRD-correct, not-yet-
        # true state) still run.
        with contextlib.suppress(IntentRejectedError):
            await submit_player_intent(
                start.handle,
                actor_id="char:hero",
                intent=PlayerIntent(
                    intent_type="attack", weapon_id="light-crossbow", target_id="mon:foe"
                ),
            )
        return live

    live = run_async(_run())
    rejections = [
        e
        for e in events_of(live, AttackFailed)
        if e.actor_id == "char:hero" and e.target_id == "mon:foe"
    ]
    assert rejections
    assert rejections[-1].reason == "weapon_already_fired"


def test_c15_s06_massive_damage_triggers_instant_death_for_a_character():
    """C15-S06: SRD 5.2 (Dropping to 0 Hit Points, Instant Death) —
    "When damage reduces a character to 0 Hit Points and damage remains,
    the character dies if the remainder equals or exceeds their Hit Point
    maximum."
    (packs/_source/content24/chapter-1/damage-and-healing.yml, id
    unGgf3TA3iSawYAn). ``Death(reason="instant_kill")`` has zero call
    sites anywhere in ``src/`` — ``apply.py``'s ``is_overkill`` flag is
    purely decorative.
    """

    async def _run():
        start = await start_combat(
            session_id="e2e-c15-s06",
            party=[
                PartyMemberSpec(
                    entity_id="char:hero",
                    name="Hero",
                    initiative=20,
                    hp_current=20,
                    hp_max=20,
                    strength=16,
                    character_level=1,
                    zone_id=cell(0, 0),
                ),
                PartyMemberSpec(
                    entity_id="char:victim",
                    name="Victim",
                    initiative=1,
                    hp_current=1,
                    hp_max=1,
                    ac=1,
                    zone_id=cell(0, 1),
                ),
            ],
            encounter=[
                EncounterMemberSpec(
                    entity_id="mon:bystander",
                    entity_type="Monster",
                    name="Bystander",
                    initiative=2,
                    hp_current=50,
                    hp_max=50,
                    ac=20,
                    zone_id=cell(5, 5),
                )
            ],
            scene_zones=None,
            grid_scene=grid_scene(),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="attack", weapon_id="dagger", target_id="char:victim"),
        )
        return live

    live = run_async(_run())
    deaths = [
        e
        for e in events_of(live, Death)
        if e.target_id == "char:victim" and e.reason == "instant_kill"
    ]
    assert deaths


@xfail_cluster(15, "attack rules")
def test_c15_s07_vex_mastery_grants_advantage_on_next_attack():
    """C15-S07: SRD 5.2 (Vex) — "If you hit a creature with this weapon
    and deal damage to the creature, you have Advantage on your next
    attack roll against that creature before the end of your next turn."
    (packs/_source/content24/appendices/appendix-d-rule-references.yml,
    id hg3adn9O1O5Z2QxL). ``apply_mastery_on_hit`` routes ``vex`` to
    ``_log_deferred`` — an info log line, no event, no ``ActiveEffect``,
    no sidecar write. Vex-granted advantage is unreachable end-to-end.
    """
    from dnd5e_engine.orchestrator import advance_monster_turn

    async def _run():
        start = await start_combat(
            session_id="e2e-c15-s07",
            party=[
                PartyMemberSpec(
                    entity_id="char:hero",
                    name="Hero",
                    initiative=20,
                    hp_current=20,
                    hp_max=20,
                    strength=16,
                    zone_id=cell(0, 0),
                )
            ],
            encounter=[
                EncounterMemberSpec(
                    entity_id="mon:foe",
                    entity_type="Monster",
                    name="Foe",
                    initiative=1,
                    hp_current=500,
                    hp_max=500,
                    ac=1,
                    zone_id=cell(0, 1),
                )
            ],
            scene_zones=None,
            grid_scene=grid_scene(),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="attack", weapon_id="shortsword", target_id="mon:foe"),
        )
        await advance_monster_turn(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="attack", weapon_id="shortsword", target_id="mon:foe"),
        )
        return live

    live = run_async(_run())
    swings = [e for e in events_of(live, AttackRolled) if e.attacker_id == "char:hero"]
    assert len(swings) == 2
    assert swings[0].advantage == "normal"
    assert swings[1].advantage == "advantage"
