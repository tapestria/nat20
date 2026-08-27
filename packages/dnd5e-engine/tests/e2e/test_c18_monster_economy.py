"""C18 — Monster action economy.

Transcribed from specs/e2e-scenario-catalog.md, Cluster 18
(specs/catalog-v2/c18.md). Grid backend only (``GridScene`` + ``cell_id``),
never zones. Real bundled corpus slugs throughout (verified live against
``BundledAssetLoader`` while drafting the catalog).
"""

from __future__ import annotations

from dnd5e_engine import PlayerIntent
from dnd5e_engine.events import AttackRolled, DamageApplied, HealingApplied, SaveRolled
from dnd5e_engine.orchestrator import (
    _get_live,
    advance_monster_turn,
    end_combat,
    start_combat,
    submit_player_intent,
)
from dnd5e_engine.specs import EncounterMemberSpec, PartyMemberSpec
from tests.e2e.harness import cell, events_of, grid_scene, run_async, xfail_cluster


@xfail_cluster(18, "monster action economy")
def test_c18_s01_recharge_gates_a_breath_weapon_ai_cannot_select_it():
    """C18-S01: SRD 5.2 "Recharge X-Y. ... At the start of each of the
    monster's turns, roll 1d6. If the roll is within the number range
    given in the notation ..., the monster regains the use of that part."
    (packs/_source/content24/monsters/monsters.yml:8551-8555, "Limited
    Usage"). ``select_typed_monster_action`` always returns ``Claw`` (the
    first offensive action in list order) on every turn — Fire Breath
    (Recharge 6) is structurally unreachable regardless of any recharge
    state, and no ``RechargeRolled`` event type exists in ``events.py``.
    """

    async def _run():
        start = await start_combat(
            session_id="e2e-c18-s01",
            party=[
                PartyMemberSpec(
                    entity_id="char:hero",
                    name="Hero",
                    initiative=1,
                    hp_current=40,
                    hp_max=40,
                    ac=12,
                    zone_id=cell(0, 0),
                )
            ],
            encounter=[
                EncounterMemberSpec(
                    entity_id="mon:mephit",
                    entity_type="Monster",
                    name="Magma Mephit",
                    initiative=20,
                    hp_current=18,
                    hp_max=18,
                    ac=11,
                    zone_id=cell(1, 0),
                    monster_template_slug="magma-mephit",
                    base_speed=30,
                )
            ],
            scene_zones=None,
            grid_scene=grid_scene(),
            rng_seed=7,
        )
        live = _get_live(start.handle)
        await advance_monster_turn(start.handle)  # mephit's turn 1
        await advance_monster_turn(start.handle)  # mephit's turn 2 (round 2)
        return live

    live = run_async(_run())

    # API delta (C18): RechargeRolled does not exist today — look it up
    # dynamically so its absence drives the xfail rather than a collection
    # error, mirroring the C16-S07 CombatantMoved idiom.
    from dnd5e_engine import events as events_module

    recharge_rolled_cls = events_module.RechargeRolled
    recharge_events = [e for e in live.event_log if isinstance(e, recharge_rolled_cls)]
    assert recharge_events, "expected a RechargeRolled roll at the start of turn 2"

    fire_breath_dmg = [
        e
        for e in events_of(live, DamageApplied)
        if e.target_id == "char:hero" and e.damage_type == "fire"
    ]
    assert fire_breath_dmg, "Fire Breath should be selectable while available (turn 1)"


@xfail_cluster(18, "monster action economy")
def test_c18_s02_legendary_actions_spent_after_pc_turn_pool_resets_on_own_turn():
    """C18-S02: SRD 5.2 "A Legendary Action is an action that a monster
    can take immediately after another creature's turn. ... The monster
    expends one use whenever it takes a Legendary Action, and it regains
    all expended uses at the start of each of its turns."
    (packs/_source/content24/monsters/monsters.yml, "Legendary Actions").
    ``advance_monster_turn(handle, legendary=True)`` raises ``TypeError``
    today — no legendary-action pool is tracked anywhere.
    """

    async def _run():
        start = await start_combat(
            session_id="e2e-c18-s02",
            party=[
                PartyMemberSpec(
                    entity_id="char:hero",
                    name="Hero",
                    initiative=25,
                    hp_current=60,
                    hp_max=60,
                    ac=18,
                    attack_bonus=7,
                    zone_id=cell(0, 0),
                )
            ],
            encounter=[
                EncounterMemberSpec(
                    entity_id="mon:dragon",
                    entity_type="Monster",
                    name="Adult Red Dragon",
                    initiative=10,
                    hp_current=256,
                    hp_max=256,
                    ac=19,
                    zone_id=cell(3, 0),
                    monster_template_slug="adult-red-dragon",
                    base_speed=40,
                )
            ],
            scene_zones=None,
            grid_scene=grid_scene(width=12, height=12),
            rng_seed=4,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(
                intent_type="attack", weapon_id="longsword", target_id="mon:dragon"
            ),
        )
        # API delta (C18): the legendary=True kwarg does not exist today —
        # this raises TypeError, driving the xfail.
        await advance_monster_turn(start.handle, legendary=True)
        await advance_monster_turn(start.handle)
        return live

    live = run_async(_run())

    from dnd5e_engine import events as events_module

    legendary_used_cls = events_module.LegendaryActionUsed
    used_events = [e for e in live.event_log if isinstance(e, legendary_used_cls)]
    assert used_events
    assert used_events[0].actor_id == "mon:dragon"


@xfail_cluster(18, "monster action economy")
def test_c18_s03_legendary_resistance_converts_failed_save_and_saves_ignore_proficiency():
    """C18-S03: SRD 5.2 "If the monster fails a saving throw, it can
    choose to succeed instead."
    (packs/_source/monsterfeatures24/traits/legendary-resistance.yml);
    "A skill bonus is the sum of a monster's relevant ability modifier
    and its Proficiency Bonus." (packs/_source/content24/monsters/monsters.yml:114-118).
    No failed->success conversion hook exists anywhere; independently,
    ``Monster.saving_throws`` is never read by the save-resolution path
    at all — ``roll_total`` reflects a flat ``+0`` even for a
    proficient-Wis dragon, dropping the stat block's ``+7`` Wis save
    entirely.

    Part 1 (same-seed A/B delta): ``adult-red-dragon`` (Wis 13, proficient,
    ``saving_throws.wis=7`` = ability mod +1 + proficiency bonus +6) vs
    ``brown-bear`` (Wis 13 too, ``saving_throws.wis=None`` — non-proficient)
    at the identical seed isolates PURELY the proficiency-bonus delta (+6):
    with matching Wis ability scores on both templates, the only variable
    left is proficiency. Today both resolve to a flat +0 (empirically
    verified: seed 9 -> natural 15 on both), so the delta is 0; SRD-correct
    it should be exactly +6 (the dragon's proficiency bonus component).

    Part 2 (fail -> Legendary-Resistance-converts): seed 2 was empirically
    verified (running the real seeded engine against this exact setup) to
    draw a natural d20 of 2 for the dragon's Wis save against DC 12 — this
    fails even under the SRD-correct proficient +7 modifier this scenario
    pins (2 + 7 = 9 < 12), so the fail-then-convert narrative holds once
    both the proficiency gap and the resistance hook land. Run A pins
    today's already-correct fail/condition-apply mechanics (no gap by
    itself); Run B exercises the presumed ``resolve_legendary_resistance``
    hook, which does not exist anywhere in ``orchestrator.py`` today.
    """

    def _run(slug: str, hp: int, ac: int, seed: int):
        async def _inner():
            start = await start_combat(
                session_id=f"e2e-c18-s03-{slug}-{seed}",
                party=[
                    PartyMemberSpec(
                        entity_id="char:wiz",
                        name="Wizard",
                        initiative=20,
                        hp_current=30,
                        hp_max=30,
                        wisdom=10,
                        character_level=9,
                        class_slug="wizard",
                        spells_known=["hold-monster"],
                        spell_slots={5: 1},
                        zone_id=cell(0, 0),
                    )
                ],
                encounter=[
                    EncounterMemberSpec(
                        entity_id="mon:dragon",
                        entity_type="Monster",
                        name="Dragon",
                        initiative=1,
                        hp_current=hp,
                        hp_max=hp,
                        ac=ac,
                        zone_id=cell(2, 0),
                        monster_template_slug=slug,
                    )
                ],
                scene_zones=None,
                grid_scene=grid_scene(),
                rng_seed=seed,
            )
            live = _get_live(start.handle)
            await submit_player_intent(
                start.handle,
                actor_id="char:wiz",
                intent=PlayerIntent(
                    intent_type="cast_spell", spell_id="hold-monster", target_id="mon:dragon"
                ),
            )
            return start.handle, live

        return run_async(_inner())

    # Part 1 — same-seed A/B: proficient dragon vs a non-proficient
    # same-Wis-ability-score brown-bear, isolating the proficiency delta.
    _, live_dragon = _run("adult-red-dragon", 256, 19, 9)
    _, live_bear = _run("brown-bear", 34, 11, 9)
    roll_dragon = next(
        e for e in events_of(live_dragon, SaveRolled) if e.target_id == "mon:dragon"
    ).roll_total
    roll_bear = next(
        e for e in events_of(live_bear, SaveRolled) if e.target_id == "mon:dragon"
    ).roll_total
    assert roll_dragon - roll_bear == 6, (
        "same natural d20 (seed 9) should differ ONLY by the dragon's +6 "
        "Wis-save proficiency bonus, not resolve identically"
    )

    # Part 2, Run A — a failed save (seed 2 -> natural 2) applies Paralyzed
    # normally; this half already works today (no gap by itself).
    from dnd5e_engine.events import ConditionApplied

    _, live_a = _run("adult-red-dragon", 256, 19, 2)
    save_a = next(e for e in events_of(live_a, SaveRolled) if e.target_id == "mon:dragon")
    assert save_a.succeeded is False
    paralyzed_a = [
        e
        for e in events_of(live_a, ConditionApplied)
        if e.target_id == "mon:dragon" and e.condition == "paralyzed"
    ]
    assert paralyzed_a

    # Part 2, Run B — identical setup/seed, but the dragon elects to spend a
    # Legendary Resistance use, converting the failure to success. API delta
    # (C18): resolve_legendary_resistance does not exist anywhere in
    # orchestrator.py today.
    from dnd5e_engine import orchestrator as orchestrator_module

    handle_b, live_b = _run("adult-red-dragon", 256, 19, 2)
    orchestrator_module.resolve_legendary_resistance(handle_b, "mon:dragon")

    from dnd5e_engine import events as events_module

    used = [
        e
        for e in live_b.event_log
        if isinstance(e, events_module.LegendaryResistanceUsed) and e.actor_id == "mon:dragon"
    ]
    assert used
    paralyzed_b = [
        e
        for e in events_of(live_b, ConditionApplied)
        if e.target_id == "mon:dragon" and e.condition == "paralyzed"
    ]
    assert not paralyzed_b, "a Legendary-Resistance-converted save must not apply the condition"


@xfail_cluster(18, "monster action economy")
def test_c18_s04_troll_regeneration_heals_at_start_of_turn_above_zero_hp():
    """C18-S04: SRD 5.2 "The [monster] regains [N] Hit Points at the
    start of each of its turns if it has at least 1 Hit Point."
    (packs/_source/monsterfeatures24/traits/regeneration.yml).
    ``advance_monster_turn`` has no turn-start heal/regeneration hook at
    all — ``Monster.special_abilities`` is read nowhere in
    ``orchestrator.py``/``activities/monster_actions.py``.
    """

    async def _run():
        start = await start_combat(
            session_id="e2e-c18-s04",
            party=[
                PartyMemberSpec(
                    entity_id="char:hero",
                    name="Hero",
                    initiative=20,
                    hp_current=40,
                    hp_max=40,
                    attack_bonus=6,
                    zone_id=cell(0, 0),
                )
            ],
            encounter=[
                EncounterMemberSpec(
                    entity_id="mon:troll",
                    entity_type="Monster",
                    name="Troll",
                    initiative=5,
                    hp_current=40,
                    hp_max=94,
                    ac=15,
                    zone_id=cell(1, 0),
                    monster_template_slug="troll",
                )
            ],
            scene_zones=None,
            grid_scene=grid_scene(),
            rng_seed=2,
        )
        live = _get_live(start.handle)
        await advance_monster_turn(start.handle)  # troll's own turn begins
        return live

    live = run_async(_run())
    heals = [e for e in events_of(live, HealingApplied) if e.target_id == "mon:troll"]
    assert heals
    assert heals[0].amount == 10


@xfail_cluster(18, "monster action economy")
def test_c18_s05_magic_resistance_grants_advantage_on_saves_vs_spells():
    """C18-S05: SRD 5.2 "The [monster] has Advantage on saving throws
    against spells and other magical effects."
    (packs/_source/monsterfeatures24/traits/magic-resistance.yml).
    ``activities/save.py``'s save-roll primitive draws exactly one
    natural d20 regardless of target — same-seed A/B: an Ogre (no Magic
    Resistance) and a Hezrou (has it) resolve byte-identically today.

    Dexterity is pinned to a non-default 11 (not the EncounterMemberSpec
    ``10`` sentinel) so F1b's monster-template ability-score hydration
    doesn't substitute the two monsters' differing SRD DEX scores — that
    would diverge the DEX-save modifier for an unrelated reason and
    falsely XPASS this xfail before Magic Resistance itself is wired up.
    """

    def _party():
        return [
            PartyMemberSpec(
                entity_id="char:wiz",
                name="Wizard",
                initiative=20,
                hp_current=30,
                hp_max=30,
                character_level=9,
                class_slug="wizard",
                spells_known=["fireball"],
                spell_slots={3: 1},
                zone_id=cell(0, 0),
            )
        ]

    async def _run(slug: str, hp: int, ac: int):
        start = await start_combat(
            session_id=f"e2e-c18-s05-{slug}",
            party=_party(),
            encounter=[
                EncounterMemberSpec(
                    entity_id="mon:foe",
                    entity_type="Monster",
                    name="Foe",
                    initiative=1,
                    hp_current=hp,
                    hp_max=hp,
                    ac=ac,
                    # 11, not the default 10: ``EncounterMemberSpec.dexterity``
                    # treats exactly 10 as "unset" when ``monster_template_slug``
                    # resolves, so 10 would silently take the template's DEX.
                    # Revert to 10 when the field is retyped ``int | None`` — see
                    # the T5 entry in BACKLOG.md's foundations follow-ups.
                    dexterity=11,
                    zone_id=cell(3, 0),
                    monster_template_slug=slug,
                )
            ],
            scene_zones=None,
            grid_scene=grid_scene(),
            rng_seed=6,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:wiz",
            intent=PlayerIntent(intent_type="cast_spell", spell_id="fireball", target_id="mon:foe"),
        )
        return live

    live_a = run_async(_run("ogre", 59, 11))
    roll_a = next(e for e in events_of(live_a, SaveRolled) if e.target_id == "mon:foe").roll_total

    live_b = run_async(_run("hezrou", 175, 17))
    roll_b = next(e for e in events_of(live_b, SaveRolled) if e.target_id == "mon:foe").roll_total

    assert roll_a != roll_b, (
        "Magic Resistance should consume an extra d20 draw (advantage), "
        "diverging the RNG stream from the non-resistant baseline"
    )


@xfail_cluster(18, "monster action economy")
def test_c18_s06_pack_tactics_grants_attack_advantage_with_adjacent_ally():
    """C18-S06: SRD 5.2 "The [monster] has Advantage on an attack roll
    against a creature if at least one of the [monster]'s allies is
    within 5 feet of the creature and the ally doesn't have the
    Incapacitated condition."
    (packs/_source/monsterfeatures24/traits/pack-tactics.yml).
    ``activities/attack.py::resolve_attack_activity`` hardcodes
    ``mode: AdvantageMode = "normal"`` (L119) unconditionally — Pack
    Tactics is consulted nowhere in the attack-roll path.
    """

    def _hero():
        return PartyMemberSpec(
            entity_id="char:hero",
            name="Hero",
            initiative=20,
            hp_current=30,
            hp_max=30,
            ac=14,
            zone_id=cell(5, 5),
        )

    def _wolf1():
        return EncounterMemberSpec(
            entity_id="mon:wolf1",
            entity_type="Monster",
            name="Wolf",
            initiative=15,
            hp_current=11,
            hp_max=11,
            ac=13,
            zone_id=cell(6, 5),
            monster_template_slug="wolf",
        )

    async def _run(encounter):
        start = await start_combat(
            session_id="e2e-c18-s06",
            party=[_hero()],
            encounter=encounter,
            scene_zones=None,
            grid_scene=grid_scene(cell_size_ft=5),
            rng_seed=3,
        )
        live = _get_live(start.handle)
        await advance_monster_turn(start.handle)  # mon:wolf1 attacks char:hero
        return live

    live_a = run_async(_run([_wolf1()]))
    rolled_a = next(e for e in events_of(live_a, AttackRolled) if e.attacker_id == "mon:wolf1")

    wolf2 = EncounterMemberSpec(
        entity_id="mon:wolf2",
        entity_type="Monster",
        name="Wolf",
        initiative=14,
        hp_current=11,
        hp_max=11,
        ac=13,
        zone_id=cell(6, 6),
        monster_template_slug="wolf",
    )
    live_b = run_async(_run([_wolf1(), wolf2]))
    rolled_b = next(e for e in events_of(live_b, AttackRolled) if e.attacker_id == "mon:wolf1")

    assert rolled_a.advantage == "normal"
    assert rolled_b.advantage == "advantage"


@xfail_cluster(18, "monster action economy")
def test_c18_s07_stat_block_spellcaster_monster_actually_casting_is_unreachable():
    """C18-S07: SRD 5.2 "If a monster can cast any spells, its stat block
    lists the spells and provides the monster's spellcasting ability,
    spell save DC ..., and spell attack bonus ..."
    (packs/_source/content24/monsters/monsters.yml:262-286,
    "Spellcasting"). ``Monster`` has no ``spellcasting`` field at all;
    ``select_typed_monster_action`` excludes ``CastActivity`` from
    "offensive" entirely, and the monster-turn path builds
    ``spell_book={}`` unconditionally.
    """

    async def _run():
        start = await start_combat(
            session_id="e2e-c18-s07",
            party=[
                PartyMemberSpec(
                    entity_id="char:hero",
                    name="Hero",
                    initiative=1,
                    hp_current=30,
                    hp_max=30,
                    ac=12,
                    zone_id=cell(0, 0),
                )
            ],
            encounter=[
                EncounterMemberSpec(
                    entity_id="mon:mage",
                    entity_type="Monster",
                    name="Mage",
                    initiative=20,
                    hp_current=40,
                    hp_max=40,
                    ac=12,
                    zone_id=cell(2, 0),
                    monster_template_slug="mage",
                )
            ],
            scene_zones=None,
            grid_scene=grid_scene(),
            rng_seed=5,
        )
        live = _get_live(start.handle)
        await advance_monster_turn(start.handle)
        return live

    live = run_async(_run())
    fire_dmg = [
        e
        for e in events_of(live, DamageApplied)
        if e.target_id == "char:hero" and e.damage_type == "fire"
    ]
    assert fire_dmg, "the mage should be able to select and cast Fireball"
    saves = [e for e in events_of(live, SaveRolled) if e.target_id == "char:hero"]
    assert saves
    assert saves[0].ability == "dex"


@xfail_cluster(18, "monster action economy")
def test_c18_s08_combat_ends_flee_when_every_foe_has_fled():
    """C18-S08: engine/Foundry-parity plumbing (no dedicated SRD flee
    mechanic) per spec §5 C18's acceptance-contract line item
    ``ended_reason="flee"``. ``_derive_ended_reason`` computes only
    ``all_foes_dead``/``all_pcs_dead`` — its return-type annotation
    already carries the ``"flee"`` literal, but no code path ever
    returns it; a live, un-dead, fled goblin still yields
    ``ended_reason == "forced"``.
    """

    async def _run():
        start = await start_combat(
            session_id="e2e-c18-s08",
            party=[
                PartyMemberSpec(
                    entity_id="char:hero",
                    name="Hero",
                    initiative=20,
                    hp_current=30,
                    hp_max=30,
                    attack_bonus=5,
                    zone_id=cell(5, 5),
                )
            ],
            encounter=[
                EncounterMemberSpec(
                    entity_id="mon:goblin",
                    entity_type="Monster",
                    name="Goblin",
                    initiative=10,
                    hp_current=1,
                    hp_max=20,
                    ac=13,
                    zone_id=cell(6, 5),
                    monster_template_slug="goblin-warrior",
                    base_speed=30,
                    behavior_profile="AGGRESSIVE",
                )
            ],
            scene_zones=None,
            grid_scene=grid_scene(),
            rng_seed=1,
        )
        handle = start.handle
        await advance_monster_turn(handle)  # below flee threshold: retreats/passes
        result = await end_combat(handle)
        return result

    result = run_async(_run())
    assert result.outcome.ended_reason == "flee"
