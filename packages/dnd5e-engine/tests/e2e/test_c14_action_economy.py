"""C14 — Action economy & turn structure.

Transcribed from specs/e2e-scenario-catalog.md, Cluster 14
(specs/catalog-v2/c14.md). Grid-only per D8 — every setup uses
``GridScene`` + ``"col,row"`` cell ids, never ``SceneTopology`` zones.
"""

from __future__ import annotations

import contextlib

from dnd5e_engine import PlayerIntent
from dnd5e_engine.events import AttackFailed, AttackRolled, CheckRolled, DamageApplied
from dnd5e_engine.orchestrator import (
    _get_live,
    advance_monster_turn,
    get_live,
    start_combat,
    submit_player_intent,
)
from dnd5e_engine.specs import EncounterMemberSpec, GridScene, PartyMemberSpec
from tests.e2e.harness import cell, events_of, grid_scene, run_async, xfail_cluster


@xfail_cluster(14, "action economy")
def test_c14_s01_dodge_disadvantages_attackers_until_next_turn():
    """C14-S01: SRD 5.2 (Dodge) — "until the start of your next turn, any
    attack roll made against you has Disadvantage if you can see the
    attacker..." (packs/_source/content24/appendices/rules-glossary.yml,
    page 3YJIuyCMmuUrfmuX, heading "Dodge"). ``dodge`` is a valid
    ``IntentType`` but ``orchestrator.py``'s dispatch chain has no handler
    for it — the intent is silently absorbed as a no-op.
    """

    def _run(dodge: bool):
        async def _inner():
            start = await start_combat(
                session_id="e2e-c14-s01",
                party=[
                    PartyMemberSpec(
                        entity_id="char:dodger",
                        name="Dodger",
                        initiative=20,
                        hp_current=30,
                        hp_max=30,
                        ac=14,
                        zone_id=cell(0, 0),
                    )
                ],
                encounter=[
                    EncounterMemberSpec(
                        entity_id="mon:foe",
                        entity_type="Monster",
                        name="Foe",
                        initiative=10,
                        hp_current=30,
                        hp_max=30,
                        ac=10,
                        attack_bonus=5,
                        zone_id=cell(1, 0),
                    )
                ],
                scene_zones=None,
                grid_scene=grid_scene(),
                rng_seed=7,
            )
            live = _get_live(start.handle)
            intent_type = "dodge" if dodge else "pass"
            await submit_player_intent(
                start.handle,
                actor_id="char:dodger",
                intent=PlayerIntent(intent_type=intent_type),
            )
            await advance_monster_turn(start.handle)
            return live

        return run_async(_inner())

    live_a = _run(False)
    live_b = _run(True)

    rolled_a = next(e for e in events_of(live_a, AttackRolled) if e.target_id == "char:dodger")
    rolled_b = next(e for e in events_of(live_b, AttackRolled) if e.target_id == "char:dodger")

    assert rolled_a.advantage == "normal"
    assert rolled_b.advantage == "disadvantage"


@xfail_cluster(14, "action economy")
def test_c14_s02_hide_grants_advantage_on_next_attack():
    """C14-S02: SRD 5.2 (Hide) — "you must succeed on a DC 15 Dexterity
    (Stealth) check while you're Heavily Obscured or behind Three-Quarters
    Cover or Total Cover... On a successful check, you have the Invisible
    condition while hidden."
    (packs/_source/content24/appendices/rules-glossary.yml, page
    rqhOsUY4wWa1oHTy, heading "Hide"). ``hide`` is a valid ``IntentType``
    with no dispatch handler — no ``CheckRolled`` fires and the follow-up
    attack stays "normal".
    """

    def _party():
        return [
            PartyMemberSpec(
                entity_id="char:rogue",
                name="Rogue",
                initiative=20,
                hp_current=20,
                hp_max=20,
                ac=14,
                dexterity=16,
                zone_id=cell(0, 0),
            )
        ]

    def _encounter():
        return [
            EncounterMemberSpec(
                entity_id="mon:foe",
                entity_type="Monster",
                name="Foe",
                initiative=1,
                hp_current=30,
                hp_max=30,
                ac=10,
                zone_id=cell(1, 0),
            )
        ]

    def _grid():
        return GridScene(width=10, height=10, cover_cells={cell(0, 0): "three_quarters"})

    async def _run_a():
        start = await start_combat(
            session_id="e2e-c14-s02-a",
            party=_party(),
            encounter=_encounter(),
            scene_zones=None,
            grid_scene=_grid(),
            rng_seed=9,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:rogue",
            intent=PlayerIntent(intent_type="attack", weapon_id="dagger", target_id="mon:foe"),
        )
        return live

    async def _run_b():
        start = await start_combat(
            session_id="e2e-c14-s02-b",
            party=_party(),
            encounter=_encounter(),
            scene_zones=None,
            grid_scene=_grid(),
            rng_seed=9,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle, actor_id="char:rogue", intent=PlayerIntent(intent_type="hide")
        )
        await submit_player_intent(
            start.handle,
            actor_id="char:rogue",
            intent=PlayerIntent(intent_type="attack", weapon_id="dagger", target_id="mon:foe"),
        )
        return live

    live_a = run_async(_run_a())
    live_b = run_async(_run_b())

    rolled_a = next(e for e in events_of(live_a, AttackRolled) if e.attacker_id == "char:rogue")
    hide_checks = [
        e
        for e in events_of(live_b, CheckRolled)
        if e.actor_id == "char:rogue" and e.skill == "stealth"
    ]
    rolled_b = next(e for e in events_of(live_b, AttackRolled) if e.attacker_id == "char:rogue")

    assert hide_checks
    assert hide_checks[0].dc == 15
    assert rolled_a.advantage == "normal"
    assert rolled_b.advantage == "advantage"


@xfail_cluster(14, "action economy")
def test_c14_s03_help_grants_advantage_to_next_ally_attack():
    """C14-S03: SRD 5.2 (Help, Assist an Attack Roll) — "You momentarily
    distract an enemy within 5 feet of you, giving Advantage to the next
    attack roll by one of your allies against that enemy."
    (packs/_source/content24/appendices/rules-glossary.yml, page
    5S8i59qskkd9GGcJ, heading "Help"). ``help`` is a valid ``IntentType``
    with no dispatch handler — both runs produce "normal".
    """

    def _run(help_: bool):
        async def _inner():
            start = await start_combat(
                session_id="e2e-c14-s03",
                party=[
                    PartyMemberSpec(
                        entity_id="char:helper",
                        name="Helper",
                        initiative=20,
                        hp_current=20,
                        hp_max=20,
                        zone_id=cell(1, 0),
                    ),
                    PartyMemberSpec(
                        entity_id="char:striker",
                        name="Striker",
                        initiative=15,
                        hp_current=20,
                        hp_max=20,
                        attack_bonus=5,
                        zone_id=cell(2, 0),
                    ),
                ],
                encounter=[
                    EncounterMemberSpec(
                        entity_id="mon:foe",
                        entity_type="Monster",
                        name="Foe",
                        initiative=1,
                        hp_current=30,
                        hp_max=30,
                        ac=10,
                        zone_id=cell(1, 1),
                    )
                ],
                scene_zones=None,
                grid_scene=grid_scene(),
                rng_seed=13,
            )
            live = _get_live(start.handle)
            if help_:
                await submit_player_intent(
                    start.handle,
                    actor_id="char:helper",
                    intent=PlayerIntent(intent_type="help", target_id="mon:foe"),
                )
            else:
                await submit_player_intent(
                    start.handle, actor_id="char:helper", intent=PlayerIntent(intent_type="pass")
                )
            await submit_player_intent(
                start.handle,
                actor_id="char:striker",
                intent=PlayerIntent(
                    intent_type="attack", weapon_id="longsword", target_id="mon:foe"
                ),
            )
            return live

        return run_async(_inner())

    live_a = _run(False)
    live_b = _run(True)

    rolled_a = next(e for e in events_of(live_a, AttackRolled) if e.attacker_id == "char:striker")
    rolled_b = next(e for e in events_of(live_b, AttackRolled) if e.attacker_id == "char:striker")

    assert rolled_a.advantage == "normal"
    assert rolled_b.advantage == "advantage"


@xfail_cluster(14, "action economy")
def test_c14_s04_grapple_shove_and_stand_up():
    """C14-S04: SRD 5.2 (Unarmed Strike, Grapple/Shove) and Ending a
    Grapple / Prone Restricted Movement
    (packs/_source/content24/appendices/rules-glossary.yml, pages
    2Uvc5myrDs18Cf19 "Unarmed Strike" and QxCrRcgMdUd3gfzz "Prone";
    packs/_source/content24/appendices/appendix-d-rule-references.yml,
    page 2TZKy9YbMN3ZY3h8 "Ending a Grapple"). Neither ``grapple`` nor
    ``shove`` nor ``stand_up`` nor ``escape_grapple`` is a member of
    ``IntentType`` today — ``PlayerIntent`` construction raises a
    validation error before any of this can be exercised.
    """

    async def _run():
        start = await start_combat(
            session_id="e2e-c14-s04",
            party=[
                PartyMemberSpec(
                    entity_id="char:brute",
                    name="Brute",
                    initiative=20,
                    hp_current=20,
                    hp_max=20,
                    strength=18,
                    character_level=5,
                    base_speed=30,
                    zone_id=cell(0, 0),
                )
            ],
            encounter=[
                EncounterMemberSpec(
                    entity_id="mon:target",
                    entity_type="Monster",
                    name="Target",
                    initiative=1,
                    hp_current=20,
                    hp_max=20,
                    ac=10,
                    dexterity=10,
                    zone_id=cell(1, 0),
                )
            ],
            scene_zones=None,
            grid_scene=grid_scene(),
            rng_seed=5,
        )
        live = _get_live(start.handle)

        # API delta (C14): "grapple" is not an IntentType member today.
        await submit_player_intent(
            start.handle,
            actor_id="char:brute",
            intent=PlayerIntent(
                intent_type="grapple", weapon_id="unarmed-strike", target_id="mon:target"
            ),
        )
        await submit_player_intent(
            start.handle, actor_id="mon:target", intent=PlayerIntent(intent_type="escape_grapple")
        )
        await submit_player_intent(
            start.handle,
            actor_id="char:brute",
            intent=PlayerIntent(
                intent_type="shove", weapon_id="unarmed-strike", target_id="mon:target"
            ),
        )
        await submit_player_intent(
            start.handle, actor_id="mon:target", intent=PlayerIntent(intent_type="stand_up")
        )
        await submit_player_intent(
            start.handle,
            actor_id="mon:target",
            intent=PlayerIntent(intent_type="move", target_zone_id=cell(4, 0)),
        )
        target = next(c for c in live.initiative if c.entity_id == "mon:target")
        return live, target

    live, target = run_async(_run())

    from dnd5e_engine.events import CheckRolled, ConditionApplied, ConditionRemoved, SaveRolled

    grapple_saves = [
        e for e in events_of(live, SaveRolled) if e.target_id == "mon:target" and e.dc == 15
    ]
    assert grapple_saves
    applied = [
        e
        for e in events_of(live, ConditionApplied)
        if e.target_id == "mon:target" and e.condition == "grappled"
    ]
    assert applied
    # The escape attempt rolls a Str(Athletics)/Dex(Acrobatics) CheckRolled
    # against the *stored* grapple DC (15), not a re-derived one.
    escape_checks = [
        e
        for e in events_of(live, CheckRolled)
        if e.actor_id == "mon:target" and e.ability in ("str", "dex") and e.dc == 15
    ]
    assert escape_checks
    removed = [
        e
        for e in events_of(live, ConditionRemoved)
        if e.target_id == "mon:target" and e.condition == "grappled"
    ]
    assert removed
    prone_applied = [
        e
        for e in events_of(live, ConditionApplied)
        if e.target_id == "mon:target" and e.condition == "prone"
    ]
    assert prone_applied
    # Standing up costs base_speed // 2 == 15 ft; at most 15 ft remains.
    assert target.movement_remaining <= 15


def test_c14_s05_extra_attack_grants_exactly_two_swings():
    """C14-S05: SRD 5.2 (Fighter, Extra Attack) — "You can attack twice
    instead of once whenever you take the Attack action on your turn."
    (classes24/fighter/class-features/extra-attack.yml, id
    phbftrExtraAttac, granted at Fighter level 5). Spec §6 row D2: "One
    ``attack`` intent per swing; ``LiveCombatView.turn.attacks_remaining``;
    action stays available until 0." ``LiveCombatView`` has no ``turn``
    field at all today, and ``orchestrator.py`` has no attacks-per-action
    counter — every ``attack`` intent resolves as an independent full
    Attack action with no cap.
    """

    async def _run():
        start = await start_combat(
            session_id="e2e-c14-s05",
            party=[
                PartyMemberSpec(
                    entity_id="char:ftr",
                    name="Fighter",
                    initiative=20,
                    hp_current=40,
                    hp_max=40,
                    strength=16,
                    attack_bonus=7,
                    character_level=5,
                    class_slug="fighter",
                    zone_id=cell(0, 0),
                )
            ],
            encounter=[
                EncounterMemberSpec(
                    entity_id="mon:dummy",
                    entity_type="Monster",
                    name="Dummy",
                    initiative=1,
                    hp_current=500,
                    hp_max=500,
                    ac=1,
                    zone_id=cell(1, 0),
                )
            ],
            scene_zones=None,
            grid_scene=grid_scene(),
            rng_seed=21,
        )
        view_before = get_live(start.handle)
        attacks_remaining_before = getattr(
            getattr(view_before, "turn", None), "attacks_remaining", None
        )

        await submit_player_intent(
            start.handle,
            actor_id="char:ftr",
            intent=PlayerIntent(intent_type="attack", weapon_id="longsword", target_id="mon:dummy"),
        )
        view_after_1 = get_live(start.handle)
        attacks_remaining_1 = getattr(
            getattr(view_after_1, "turn", None), "attacks_remaining", None
        )

        # Empirically, today's engine calls ``_advance_turn`` unconditionally
        # after any (non-bonus-action) attack — with no attacks-per-action
        # counter, a second/third same-turn attack intent is rejected as
        # "not_actor_turn" rather than resolving (or being capped by an
        # extra-attack-aware "no_action_economy"). Swallow so the assertions
        # below — which pin the SRD-correct, not-yet-true state — still run.
        for _ in range(2):
            with contextlib.suppress(Exception):
                await submit_player_intent(
                    start.handle,
                    actor_id="char:ftr",
                    intent=PlayerIntent(
                        intent_type="attack", weapon_id="longsword", target_id="mon:dummy"
                    ),
                )

        live = _get_live(start.handle)
        return live, attacks_remaining_before, attacks_remaining_1

    live, before, after_1 = run_async(_run())

    assert before == 2
    assert after_1 == 1

    swings = [e for e in events_of(live, AttackRolled) if e.attacker_id == "char:ftr"]
    assert len(swings) == 2
    rejections = [
        e
        for e in events_of(live, AttackFailed)
        if e.actor_id == "char:ftr" and e.reason == "no_action_economy"
    ]
    assert rejections


def test_c14_s06_light_weapon_bonus_action_offhand_omits_positive_ability_mod():
    """C14-S06: SRD 5.2 (Light property) — "When you take the Attack
    action on your turn and attack with a Light weapon, you can make one
    extra attack as a Bonus Action later on the same turn... you don't add
    your ability modifier to the extra attack's damage unless that
    modifier is negative."
    (packs/_source/content24/chapter-6/equipment.yml, Properties section,
    "Light" heading). No bonus-action off-hand attack path exists —
    ``orchestrator.py`` has no bonus-action-economy gate keyed on a prior
    Light-weapon Attack-action swing.
    """

    async def _run():
        start = await start_combat(
            session_id="e2e-c14-s06",
            party=[
                PartyMemberSpec(
                    entity_id="char:duelist",
                    name="Duelist",
                    initiative=20,
                    hp_current=20,
                    hp_max=20,
                    strength=16,
                    attack_bonus=5,
                    zone_id=cell(0, 0),
                )
            ],
            encounter=[
                EncounterMemberSpec(
                    entity_id="mon:dummy",
                    entity_type="Monster",
                    name="Dummy",
                    initiative=1,
                    hp_current=500,
                    hp_max=500,
                    ac=1,
                    zone_id=cell(1, 0),
                )
            ],
            scene_zones=None,
            grid_scene=grid_scene(),
            # Setup repair 2026-09-01: seed 23 rolled a natural-1 off-hand fumble; assertions unchanged (catalog repair protocol).
            rng_seed=24,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:duelist",
            intent=PlayerIntent(
                intent_type="attack", weapon_id="shortsword", target_id="mon:dummy"
            ),
        )
        # Presumed bonus-action off-hand swing — today's engine calls
        # ``_advance_turn`` unconditionally after the main-hand attack
        # (empirically verified: no bonus-action-economy gate exists for
        # this path), so this second same-turn "attack" intent is rejected
        # as "not_actor_turn" rather than resolving as the Light-weapon
        # off-hand swing the rule requires.
        with contextlib.suppress(Exception):
            await submit_player_intent(
                start.handle,
                actor_id="char:duelist",
                intent=PlayerIntent(
                    intent_type="attack", weapon_id="dagger", target_id="mon:dummy"
                ),
            )
        return live

    live = run_async(_run())
    dummy_damage = [e for e in events_of(live, DamageApplied) if e.target_id == "mon:dummy"]
    # One hit from the main-hand shortsword, one from the off-hand dagger —
    # today's rejection of the second same-turn attack means only the first
    # ever lands.
    assert len(dummy_damage) == 2
    offhand = dummy_damage[-1]
    # Off-hand dagger damage with no (positive) ability modifier: raw 1d4, [1, 4].
    assert 1 <= offhand.amount <= 4


@xfail_cluster(14, "action economy")
def test_c14_s07_engine_rolls_initiative_and_surprise_applies_disadvantage():
    """C14-S07: SRD 5.2 (Initiative) — "every participant rolls
    Initiative; they make a Dexterity check that determines their place in
    the Initiative order." (packs/_source/content24/chapter-1/combat.yml,
    page FUH9AHeKlTFzC1L9); Surprise — "that creature is surprised, which
    causes it to have Disadvantage on its Initiative roll."
    (packs/_source/content24/appendices/appendix-d-rule-references.yml,
    page YmOt8HderKveA19K). ``PartyMemberSpec.initiative`` /
    ``EncounterMemberSpec.initiative`` are required ``int`` fields with no
    ``None``/optional path — passing ``initiative=None`` raises a
    validation error before any roll can happen.
    """

    def _party_kwargs(entity_id: str, name: str, zone: str, surprised: bool) -> dict:
        kwargs: dict = dict(
            entity_id=entity_id,
            name=name,
            initiative=None,  # API delta (C14): widen to int | None.
            dexterity=16,
            hp_current=20,
            hp_max=20,
            zone_id=zone,
        )
        if surprised:
            # API delta (C14): is_surprised does not exist on PartyMemberSpec
            # today — ConfigDict(extra="forbid") rejects it.
            kwargs["is_surprised"] = True
        return kwargs

    def _run(ambushed_surprised: bool):
        async def _inner():
            start = await start_combat(
                session_id="e2e-c14-s07",
                party=[
                    PartyMemberSpec(**_party_kwargs("char:aware", "Aware", cell(0, 0), False)),
                    PartyMemberSpec(
                        **_party_kwargs("char:ambushed", "Ambushed", cell(1, 0), ambushed_surprised)
                    ),
                ],
                encounter=[
                    EncounterMemberSpec(
                        entity_id="mon:foe",
                        entity_type="Monster",
                        name="Foe",
                        initiative=None,  # type: ignore[arg-type]
                        dexterity=10,
                        hp_current=20,
                        hp_max=20,
                        ac=10,
                        zone_id=cell(2, 0),
                    )
                ],
                scene_zones=None,
                grid_scene=grid_scene(),
                rng_seed=29,
            )
            live = _get_live(start.handle)
            aware = next(c for c in live.initiative if c.entity_id == "char:aware")
            ambushed = next(c for c in live.initiative if c.entity_id == "char:ambushed")
            return aware.initiative, ambushed.initiative

        return run_async(_inner())

    aware_a, ambushed_a = _run(False)
    aware_b, ambushed_b = _run(True)

    # DEX 16 -> +3 mod; engine-rolled initiative bound [1+3, 20+3].
    assert 4 <= aware_a <= 23
    assert 4 <= ambushed_a <= 23
    assert 4 <= aware_b <= 23
    # Disadvantage keeps the lower of two draws — the surprised combatant's
    # Run B seat can only be <= its unsurprised Run A seat, while the
    # unrelated Aware combatant's draw is unaffected across both runs.
    assert ambushed_b <= ambushed_a
    assert aware_a == aware_b
