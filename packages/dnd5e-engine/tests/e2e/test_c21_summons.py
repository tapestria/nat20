"""C21 — Summons, transform, enchant.

Transcribed from specs/e2e-scenario-catalog.md, Cluster 21
(specs/catalog-v2/c21.md). Every scenario is a same-seed A/B or single-
run "assert nothing happens today" probe against CURRENT public specs
and real corpus slugs — no scenario requires the additive API to exist
in order to be constructible; all of them show the gap by asserting on
absence (or, once an API delta lands, by asserting the presence that
delta introduces).
"""

from __future__ import annotations

from dnd5e_engine import ActiveEffect, ActiveEffectDuration, PlayerIntent
from dnd5e_engine.events import (
    AttackRolled,
    ConcentrationDropped,
    DamageApplied,
    EffectApplied,
    SaveRolled,
)
from dnd5e_engine.orchestrator import (
    _get_live,
    advance_monster_turn,
    start_combat,
    submit_player_intent,
)
from dnd5e_engine.specs import EncounterMemberSpec, GridScene, PartyMemberSpec
from tests.e2e.harness import cell, events_of, run_async, xfail_cluster


@xfail_cluster(21, "summons, transform, enchant")
def test_c21_s01_summon_dragon_casts_with_zero_roster_growth():
    """C21-S01: SRD 5.2 §Spell Descriptions (Summon Dragon) — "It
    manifests in an unoccupied space... In combat, the creature shares
    your Initiative count, but it takes its turn immediately after
    yours." ``resolver.py`` routes ``SummonActivity`` to an
    ``_LOGGER.info`` narrative no-op; ``start_combat`` builds a fixed
    roster once, with no mid-combat roster-add path.
    """

    async def _run():
        start = await start_combat(
            session_id="e2e-c21-s01",
            party=[
                PartyMemberSpec(
                    entity_id="char:druid",
                    name="Druid",
                    initiative=20,
                    hp_current=60,
                    hp_max=60,
                    character_level=9,
                    spells_known=["summon-dragon"],
                    spell_slots={5: 1},
                    zone_id=cell(0, 0),
                )
            ],
            encounter=[
                EncounterMemberSpec(
                    entity_id="mon:foe",
                    entity_type="Monster",
                    name="Foe",
                    initiative=5,
                    hp_current=100,
                    hp_max=100,
                    ac=15,
                    zone_id=cell(2, 0),
                )
            ],
            scene_zones=None,
            grid_scene=GridScene(width=10, height=10, wall_segments=[]),
            rng_seed=7,
        )
        live = _get_live(start.handle)
        roster_before = len(live.initiative)
        await submit_player_intent(
            start.handle,
            actor_id="char:druid",
            intent=PlayerIntent(
                intent_type="cast_spell", spell_id="summon-dragon", target_id="mon:foe"
            ),
        )
        return live, roster_before

    live, roster_before = run_async(_run())

    assert roster_before == 2
    # API delta (C21): a real summon should add a "summon:*"-style combatant.
    assert len(live.initiative) > roster_before
    assert any(c.entity_id.startswith("summon:") for c in live.initiative)


@xfail_cluster(21, "summons, transform, enchant")
def test_c21_s02_losing_concentration_dismisses_the_summoned_dragon():
    """C21-S02: SRD 5.2 §Spell Descriptions (Summon Dragon) — "The
    creature disappears when it drops to 0 Hit Points or when the spell
    ends." ``_drop_concentration`` cascades ``ConcentrationDropped`` +
    ``EffectExpired`` + ``ConditionRemoved`` today, but it does not
    know about summoned combatants because none can exist yet (per
    C21-S01) — there is no ``CombatantLeft`` event at all.

    Empirically verified in this worktree (``uv run python`` probe
    against the real seeded engine, ``rng_seed`` 1-29): casting
    ``summon-dragon`` alone registers NO ``concentration_chain`` entry
    at all, because the ``summon``-kind activity resolves to a
    narrative no-op (per C21-S01) that never creates an ``ActiveEffect``
    — so no seed ever produces a Constitution save from
    ``mon:breaker``'s hit; the concentration-check mechanism the
    catalog's "if the save fails by seed" hedge presumes never even
    fires. To exercise the REAL, already-working half of this scenario
    (does an existing concentration effect actually break on damage),
    an ``ActiveEffect(flags={"concentration": True})`` is seeded on
    ``char:druid`` at ``start_combat`` time — standing in for the
    concentration link ``summon-dragon``'s cast SHOULD have registered
    — via the same ``active_effects=`` seam C12/C13 use.
    ``monster_template_slug="hill-giant"`` is required for
    ``mon:breaker`` to attack at all: a monster with no
    ``monster_template_slug`` has no typed action repertoire and
    resolves its turn to a bare ``pass`` (``advance_monster_turn``
    only reads ``Monster.actions`` off the lib loader by slug — the
    legacy flat ``attack_bonus``/``damage_dice`` fields on
    ``EncounterMemberSpec`` are read nowhere in that path). With both
    fixes, ``rng_seed=4`` was empirically confirmed to produce a single
    Tree Club hit (17 damage) and a failed CON save
    (``roll_total=5`` vs ``dc=10``) — a real ``ConcentrationDropped``.
    """

    async def _run():
        start = await start_combat(
            session_id="e2e-c21-s02",
            party=[
                PartyMemberSpec(
                    entity_id="char:druid",
                    name="Druid",
                    initiative=20,
                    hp_current=15,
                    hp_max=15,
                    character_level=9,
                    spells_known=["summon-dragon"],
                    spell_slots={5: 1},
                    zone_id=cell(0, 0),
                )
            ],
            encounter=[
                EncounterMemberSpec(
                    entity_id="mon:foe",
                    entity_type="Monster",
                    name="Foe",
                    initiative=5,
                    hp_current=100,
                    hp_max=100,
                    ac=15,
                    zone_id=cell(2, 0),
                ),
                EncounterMemberSpec(
                    entity_id="mon:breaker",
                    entity_type="Monster",
                    name="Breaker",
                    initiative=19,
                    hp_current=100,
                    hp_max=100,
                    ac=1,
                    monster_template_slug="hill-giant",
                    zone_id=cell(1, 0),
                ),
            ],
            scene_zones=None,
            grid_scene=GridScene(width=10, height=10, wall_segments=[]),
            active_effects=[
                # Stands in for the concentration link summon-dragon's
                # cast SHOULD register today (per C21-S01, it doesn't).
                ActiveEffect(
                    id="effect:summon-dragon-concentration",
                    name="Summon Dragon",
                    origin="cast:summon-dragon:char:druid",
                    target_id="char:druid",
                    duration=ActiveEffectDuration(rounds=10),
                    flags={"concentration": True},
                ),
            ],
            rng_seed=4,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:druid",
            intent=PlayerIntent(
                intent_type="cast_spell", spell_id="summon-dragon", target_id="mon:foe"
            ),
        )
        roster_before_hit = len(live.initiative)
        await advance_monster_turn(start.handle)  # mon:breaker attacks char:druid
        return live, roster_before_hit

    live, roster_before_hit = run_async(_run())

    assert events_of(live, ConcentrationDropped), (
        "rng_seed=4 is empirically verified (see docstring) to fail "
        "char:druid's concentration save against mon:breaker's hit"
    )

    # API delta (C21): CombatantLeft does not exist on events.py today —
    # its absence (via AttributeError) drives this scenario's xfail
    # regardless of the roster-shrink assertion below.
    from dnd5e_engine import events as events_module

    combatant_left_cls = events_module.CombatantLeft
    left_events = [
        e
        for e in live.event_log
        if isinstance(e, combatant_left_cls) and e.reason == "concentration_drop"
    ]
    assert left_events, "a dismissed summon should leave the roster on ConcentrationDropped"
    assert len(live.initiative) < roster_before_hit


@xfail_cluster(21, "summons, transform, enchant")
def test_c21_s03_spiritual_weapon_casts_with_no_attack_roll():
    """C21-S03: SRD 5.2 §Spell Descriptions (Spiritual Weapon) — "you
    can immediately make one melee spell attack against one creature
    within 5 feet of the force." ``spiritual-weapon.json`` has a single
    ``summon``-kind activity with no separate ``attack``-kind
    sub-activity — the melee spell attack is not currently resolvable
    at all.
    """

    async def _run():
        start = await start_combat(
            session_id="e2e-c21-s03",
            party=[
                PartyMemberSpec(
                    entity_id="char:cleric",
                    name="Cleric",
                    initiative=15,
                    hp_current=40,
                    hp_max=40,
                    character_level=5,
                    spells_known=["spiritual-weapon"],
                    spell_slots={2: 1},
                    zone_id=cell(0, 0),
                )
            ],
            encounter=[
                EncounterMemberSpec(
                    entity_id="mon:foe",
                    entity_type="Monster",
                    name="Foe",
                    initiative=3,
                    hp_current=50,
                    hp_max=50,
                    ac=1,
                    zone_id=cell(0, 1),
                )
            ],
            scene_zones=None,
            grid_scene=GridScene(width=5, height=5, wall_segments=[]),
            rng_seed=9,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:cleric",
            intent=PlayerIntent(
                intent_type="cast_spell", spell_id="spiritual-weapon", target_id="mon:foe"
            ),
        )
        return live

    live = run_async(_run())

    # API delta (C21): a synthesized melee spell-attack path should fire an
    # AttackRolled + DamageApplied against the adjacent AC-1 target.
    attacks = [e for e in events_of(live, AttackRolled) if e.target_id == "mon:foe"]
    dmg = [e for e in events_of(live, DamageApplied) if e.target_id == "mon:foe"]
    assert attacks
    assert dmg


@xfail_cluster(21, "summons, transform, enchant")
def test_c21_s04_magic_weapon_enchant_grants_plus1_to_hit_and_damage():
    """C21-S04: SRD 5.2 §Spell Descriptions (Magic Weapon) — "that
    weapon becomes a magic weapon with a +1 bonus to attack rolls and
    damage rolls." ``resolver.py`` routes ``EnchantActivity`` to the
    same narrative no-op as every other summon-family kind — no
    ``ActiveEffect`` is ever created via
    ``activities/effects.py::apply_activity_effects``.
    """

    def _run(*, enchant: bool):
        async def _inner():
            start = await start_combat(
                session_id=f"e2e-c21-s04-{enchant}",
                party=[
                    PartyMemberSpec(
                        entity_id="char:hero",
                        name="Hero",
                        initiative=20,
                        hp_current=30,
                        hp_max=30,
                        attack_bonus=5,
                        strength=16,
                        character_level=5,
                        spells_known=["magic-weapon"],
                        spell_slots={2: 1},
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
                        zone_id=cell(0, 0),
                    )
                ],
                scene_zones=None,
                grid_scene=GridScene(width=5, height=5, wall_segments=[]),
                rng_seed=11,
            )
            live = _get_live(start.handle)
            if enchant:
                await submit_player_intent(
                    start.handle,
                    actor_id="char:hero",
                    intent=PlayerIntent(
                        intent_type="cast_spell", spell_id="magic-weapon", target_id="char:hero"
                    ),
                )
            await submit_player_intent(
                start.handle,
                actor_id="char:hero",
                intent=PlayerIntent(
                    intent_type="attack", weapon_id="longsword", target_id="mon:foe"
                ),
            )
            return live

        return run_async(_inner())

    live_a = _run(enchant=False)
    live_b = _run(enchant=True)

    assert not events_of(live_a, EffectApplied)
    # API delta (C21): EnchantActivity should route through apply_activity_effects.
    assert events_of(live_b, EffectApplied)

    base_total = sum(e.amount for e in events_of(live_a, DamageApplied) if e.target_id == "mon:foe")
    enchanted_total = sum(
        e.amount for e in events_of(live_b, DamageApplied) if e.target_id == "mon:foe"
    )
    assert enchanted_total > base_total


@xfail_cluster(21, "summons, transform, enchant")
def test_c21_s05_wild_shape_does_not_swap_stat_block_today():
    """C21-S05: SRD 5.2 §Class Features (Wild Shape) — "Your game
    statistics are replaced by the Beast's stat block... you gain a
    number of Temporary Hit Points equal to your Druid level."
    ``resolver.py`` routes ``TransformActivity`` to the narrative
    no-op; the schema already models it fully via ``TransformActivity``/
    ``TransformProfile``, but nothing consumes it.
    """

    async def _run():
        start = await start_combat(
            session_id="e2e-c21-s05",
            party=[
                PartyMemberSpec(
                    entity_id="char:druid",
                    name="Druid",
                    initiative=18,
                    hp_current=40,
                    hp_max=40,
                    character_level=6,
                    class_slug="druid",
                    zone_id=cell(0, 0),
                )
            ],
            encounter=[
                EncounterMemberSpec(
                    entity_id="mon:breaker",
                    entity_type="Monster",
                    name="Breaker",
                    initiative=10,
                    hp_current=50,
                    hp_max=50,
                    ac=10,
                    attack_bonus=10,
                    damage_dice="8d6",
                    zone_id=cell(0, 1),
                )
            ],
            scene_zones=None,
            grid_scene=GridScene(width=5, height=5, wall_segments=[]),
            rng_seed=13,
        )
        live0 = _get_live(start.handle)
        baseline = next(c for c in live0.initiative if c.entity_id == "char:druid")
        await submit_player_intent(
            start.handle,
            actor_id="char:druid",
            intent=PlayerIntent(
                intent_type="use_feature", feature_id="wild-shape", target_id="char:druid"
            ),
        )
        live1 = _get_live(start.handle)
        after_shape = next(c for c in live1.initiative if c.entity_id == "char:druid")
        await advance_monster_turn(start.handle)
        return baseline, after_shape, live1

    baseline, after_shape, live1 = run_async(_run())

    # API delta (C21): Wild Shape should grant temp HP and swap AC/attack.
    assert live1.tracked_temp_hp.get("char:druid", 0) == 6
    assert after_shape.ac != baseline.ac


@xfail_cluster(21, "summons, transform, enchant")
def test_c21_s06_polymorph_save_kind_resolves_save_but_no_transform_effect():
    """C21-S06: SRD 5.2 §Spell Descriptions (Polymorph) — "The target
    must succeed on a Wisdom saving throw or shape-shift into a Beast
    form for the duration... gains Temporary Hit Points equal to the
    Hit Points of the Beast form." Polymorph is ``save``-kind, not
    ``transform``-kind (confirmed via corpus-wide grep) — the save/DC
    half works via ``resolve_save``, but nothing implements the
    stat-block-swap-with-temp-HP-overlay consequence of a failed save.

    Empirically verified in this worktree (``uv run python`` probe
    against the real seeded engine, ``rng_seed`` 1-29, this exact
    setup): ``rng_seed=17`` actually produces a SUCCEEDED save
    (``roll_total=17`` vs ``dc=10``), not a failure as the catalog's
    original placeholder seed assumed. ``rng_seed=1`` was empirically
    confirmed to draw a natural roll totalling 5 against ``dc=10`` — a
    real failed Wisdom save (mon:foe's WIS modifier is +0: no
    per-ability save bonus is representable on ``EncounterMemberSpec``
    today, per C18-S03's finding).
    """

    async def _run():
        start = await start_combat(
            session_id="e2e-c21-s06",
            party=[
                PartyMemberSpec(
                    entity_id="char:wiz",
                    name="Wizard",
                    initiative=20,
                    hp_current=30,
                    hp_max=30,
                    character_level=9,
                    spells_known=["polymorph"],
                    spell_slots={4: 1},
                    zone_id=cell(0, 0),
                )
            ],
            encounter=[
                EncounterMemberSpec(
                    entity_id="mon:foe",
                    entity_type="Monster",
                    name="Foe",
                    initiative=5,
                    hp_current=40,
                    hp_max=40,
                    ac=10,
                    zone_id=cell(1, 0),
                )
            ],
            scene_zones=None,
            grid_scene=GridScene(width=5, height=5, wall_segments=[]),
            rng_seed=1,
        )
        live0 = _get_live(start.handle)
        baseline = next(c for c in live0.initiative if c.entity_id == "mon:foe")
        await submit_player_intent(
            start.handle,
            actor_id="char:wiz",
            intent=PlayerIntent(
                intent_type="cast_spell", spell_id="polymorph", target_id="mon:foe"
            ),
        )
        live1 = _get_live(start.handle)
        return baseline, live1

    baseline, live1 = run_async(_run())

    saves = [e for e in events_of(live1, SaveRolled) if e.target_id == "mon:foe"]
    assert saves
    assert saves[0].ability == "wis"

    after = next(c for c in live1.initiative if c.entity_id == "mon:foe")
    assert saves[0].succeeded is False, (
        "rng_seed=1 is empirically verified (see docstring) to fail mon:foe's Wisdom save"
    )
    # API delta (C21): a failed save should grant temp HP + a stat swap;
    # neither consumer exists today regardless of the save's outcome.
    assert live1.tracked_temp_hp.get("mon:foe", 0) > 0
    assert after.ac != baseline.ac
