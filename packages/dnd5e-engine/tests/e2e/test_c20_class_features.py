"""C20 — Class feature mechanics.

Transcribed from specs/e2e-scenario-catalog.md, Cluster 20
(specs/catalog-v2/c20.md). Grid-only setups (``GridScene`` + ``cell_id``),
same-seed A/B for every rider/bonus delta. Contract repairs S03, S04,
S06, S07, S08, S09, S10 and S11 were approved on 2026-09-24 (C20 plan R1).
"""

from __future__ import annotations

import random

import pytest

from dnd5e_engine import PlayerIntent
from dnd5e_engine.events import AttackRolled, DamageApplied
from dnd5e_engine.orchestrator import (
    IntentRejectedError,
    _get_live,
    advance_monster_turn,
    start_combat,
    submit_player_intent,
)
from dnd5e_engine.rules.dice import roll_d6
from dnd5e_engine.specs import EncounterMemberSpec, PartyMemberSpec
from tests.e2e.harness import cell, events_of, grid_scene, run_async, xfail_cluster


@xfail_cluster(20, "class feature mechanics")
def test_c20_s01_fighting_style_defense_grants_plus1_ac_while_armored():
    """C20-S01: SRD 5.2 ``feats24/fighting-style-feats/defense.yml``
    (identifier: defense) — "While you're wearing Light, Medium, or
    Heavy armor, you gain a +1 bonus to Armor Class."
    ``CharacterBuildSpec.selected_choices`` is accepted by the pydantic
    model but ``build_party_member`` never reads it — a fully dead
    write-only carrier; ``feats/defense.json`` itself ships
    ``activities: []`` ("not automated").
    """
    from dnd5e_srd_data.loader import BundledAssetLoader

    from dnd5e_engine.build_party import build_party_member
    from dnd5e_engine.build_spec import CharacterBuildSpec, CombatInstance

    def _run(selected_choices: tuple[str, ...]):
        async def _inner():
            spec = CharacterBuildSpec(
                species_slug="human",
                class_slug="fighter",
                level=1,
                selected_choices=selected_choices,
                equipment=("chain-mail",),
            )
            party_spec = build_party_member(
                spec,
                CombatInstance(
                    entity_id="char:hero", name="Hero", hp_current=12, hp_max=12, zone_id=cell(0, 0)
                ),
                loader=BundledAssetLoader(),
            )
            start = await start_combat(
                session_id="e2e-c20-s01",
                party=[party_spec],
                encounter=[
                    EncounterMemberSpec(
                        entity_id="mon:foe",
                        entity_type="Monster",
                        name="Foe",
                        initiative=1,
                        hp_current=1,
                        hp_max=1,
                        ac=1,
                        zone_id=cell(1, 0),
                    )
                ],
                scene_zones=None,
                grid_scene=grid_scene(width=5, height=5),
                rng_seed=1,
            )
            live = _get_live(start.handle)
            return next(c for c in live.initiative if c.entity_id == "char:hero").ac

        return run_async(_inner())

    base_ac = _run(())
    buffed_ac = _run(
        ("defense",)
    )  # API delta (C20): fighting_style routed through selected_choices

    assert buffed_ac == base_ac + 1


@xfail_cluster(20, "class feature mechanics")
def test_c20_s02_fighting_style_archery_adds_plus2_ranged_attack():
    """C20-S02: SRD 5.2 ``feats24/fighting-style-feats/archery.yml`` —
    "You gain a +2 bonus to attack rolls you make with Ranged weapons."
    There is no ``fighting_style`` field anywhere on
    ``PartyMemberSpec``/``Combatant`` today, and ``feats/archery.json``
    ships ``activities: []``, ``passive_effects: []``.
    """

    def _run(fighting_style: str | None):
        async def _inner():
            start = await start_combat(
                session_id="e2e-c20-s02",
                party=[
                    PartyMemberSpec(
                        entity_id="char:hero",
                        name="Hero",
                        initiative=20,
                        hp_current=20,
                        hp_max=20,
                        attack_bonus=5,
                        dexterity=10,
                        zone_id=cell(0, 0),
                        fighting_style=fighting_style,  # API delta (C20)
                    )
                ],
                encounter=[
                    EncounterMemberSpec(
                        entity_id="mon:foe",
                        entity_type="Monster",
                        name="Foe",
                        initiative=1,
                        hp_current=50,
                        hp_max=50,
                        ac=16,
                        zone_id=cell(6, 0),
                    )
                ],
                scene_zones=None,
                grid_scene=grid_scene(),
                rng_seed=7,
            )
            live = _get_live(start.handle)
            await submit_player_intent(
                start.handle,
                actor_id="char:hero",
                intent=PlayerIntent(
                    intent_type="attack", weapon_id="shortbow", target_id="mon:foe"
                ),
            )
            return next(e for e in events_of(live, AttackRolled) if e.attacker_id == "char:hero")

        return run_async(_inner())

    base_to_hit = _run(None).roll_total
    buffed_to_hit = _run("archery").roll_total

    assert buffed_to_hit == base_to_hit + 2


@xfail_cluster(20, "class feature mechanics")
def test_c20_s03_fighting_style_great_weapon_fighting_floors_1_2_damage_dice_at_3():
    """C20-S03: SRD 5.2 ``feats24/fighting-style-feats/great-weapon-fighting.yml``
    — "you can treat any 1 or 2 on a damage die as a 3." Foundry's own
    note: "This effect is not automated." ``great-weapon-fighting.json``
    ships ``activities: []``, ``passive_effects: []`` and no per-die
    floor logic exists anywhere under ``activities/dice.py`` or
    ``activities/damage.py``.

    ``buffed_total - base_total`` must equal the exact sum of
    ``(3 - raw_die)`` over every raw die in ``{1, 2}`` from the SAME
    seed's underlying 2d6 roll (never negative per die, never applied
    to dice showing 3-6) — per the catalog's own "pin the seed's raw
    die values via a direct ``rules/dice.py`` reseed-and-roll probe"
    technique. Contract repair (plan R1): seed 22, whose 2d6 — drawn after
    the attack's d20 — shows a 2 and a 1; the probe skips that d20.
    """

    def _run(fighting_style: str | None):
        async def _inner():
            start = await start_combat(
                session_id="e2e-c20-s03",
                party=[
                    PartyMemberSpec(
                        entity_id="char:hero",
                        name="Hero",
                        initiative=20,
                        hp_current=20,
                        hp_max=20,
                        attack_bonus=8,
                        strength=16,
                        equipment=("greatsword",),
                        zone_id=cell(0, 0),
                        fighting_style=fighting_style,  # API delta (C20)
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
                grid_scene=grid_scene(width=5, height=5),
                rng_seed=22,
            )
            live = _get_live(start.handle)
            await submit_player_intent(
                start.handle,
                actor_id="char:hero",
                intent=PlayerIntent(
                    intent_type="attack", weapon_id="greatsword", target_id="mon:foe"
                ),
            )
            return sum(e.amount for e in events_of(live, DamageApplied) if e.target_id == "mon:foe")

        return run_async(_inner())

    base_total = _run(None)
    buffed_total = _run("great-weapon-fighting")

    # Reseed-and-roll probe (catalog's own sanctioned technique): pin the
    # raw 2d6 this seed produces so the delta assertion is exact, not a
    # bare inequality. The attack's d20 is the stream's first draw.
    probe = random.Random(22)
    probe.randint(1, 20)
    raw_dice = roll_d6(count=2, rng=probe).dice
    expected_delta = sum(max(0, 3 - d) for d in raw_dice if d in (1, 2))

    assert buffed_total > base_total
    assert buffed_total - base_total == expected_delta


@xfail_cluster(20, "class feature mechanics")
def test_c20_s04_fighting_style_two_weapon_fighting_adds_ability_mod_to_offhand():
    """C20-S04: SRD 5.2 ``feats24/fighting-style-feats/two-weapon-fighting.yml``
    — "you can add your ability modifier to the damage of that attack
    if you aren't already adding it." Foundry: "not automated. You can
    add your modifier in the Situational Bonus field."
    ``two-weapon-fighting.json`` ships ``activities: []``,
    ``passive_effects: []``; the engine's off-hand extra-attack damage
    formula already correctly omits the ability mod but has no flag to
    re-add it for this feat. Contract repair (plan R1): SRD 5.2 Light —
    "That extra attack must be made with a different Light weapon", so the
    off-hand is a Dagger (Light, Finesse: DEX is its ability modifier).
    """

    def _run(fighting_style: str | None):
        async def _inner():
            start = await start_combat(
                session_id="e2e-c20-s04",
                party=[
                    PartyMemberSpec(
                        entity_id="char:hero",
                        name="Hero",
                        initiative=20,
                        hp_current=20,
                        hp_max=20,
                        attack_bonus=6,
                        dexterity=18,
                        equipment=("shortsword", "dagger"),
                        zone_id=cell(0, 0),
                        fighting_style=fighting_style,  # API delta (C20)
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
                grid_scene=grid_scene(width=5, height=5),
                rng_seed=9,
            )
            live = _get_live(start.handle)
            await submit_player_intent(
                start.handle,
                actor_id="char:hero",
                intent=PlayerIntent(
                    intent_type="attack", weapon_id="shortsword", target_id="mon:foe"
                ),
            )
            await submit_player_intent(
                start.handle,
                actor_id="char:hero",
                intent=PlayerIntent(
                    intent_type="attack",
                    weapon_id="dagger",
                    target_id="mon:foe",
                    use_bonus_action=True,
                ),
            )
            dmg = [e for e in events_of(live, DamageApplied) if e.target_id == "mon:foe"]
            return dmg[-1].amount if dmg else 0

        return run_async(_inner())

    base_offhand = _run(None)
    buffed_offhand = _run("two-weapon-fighting")

    assert buffed_offhand == base_offhand + 4


@xfail_cluster(20, "class feature mechanics")
def test_c20_s05_martial_arts_unarmed_strike_uses_scaling_die_and_dex():
    """C20-S05: SRD 5.2 ``classes24/monk/class-features/martial-arts.yml``
    (phbmnkMartialArt) — "roll 1d6 in place of the normal damage of
    your Unarmed Strike... use your Dexterity modifier instead of your
    Strength modifier." ``martial-arts.json``'s two activities are BOTH
    ``enchant``-kind, which ``activities/resolver.py`` explicitly
    leaves unresolved.
    """

    def _run(strength: int, dexterity: int):
        async def _inner():
            start = await start_combat(
                session_id="e2e-c20-s05",
                party=[
                    PartyMemberSpec(
                        entity_id="char:monk",
                        name="Monk",
                        initiative=20,
                        hp_current=20,
                        hp_max=20,
                        class_slug="monk",
                        character_level=1,
                        strength=strength,
                        dexterity=dexterity,
                        attack_bonus=4,
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
                grid_scene=grid_scene(width=5, height=5),
                rng_seed=2,
            )
            live = _get_live(start.handle)
            await submit_player_intent(
                start.handle,
                actor_id="char:monk",
                intent=PlayerIntent(
                    intent_type="attack", weapon_id="unarmed-strike", target_id="mon:foe"
                ),
            )
            return sum(e.amount for e in events_of(live, DamageApplied) if e.target_id == "mon:foe")

        return run_async(_inner())

    str_total = _run(strength=18, dexterity=8)
    dex_total = _run(strength=8, dexterity=18)

    assert 5 <= str_total <= 10
    assert 5 <= dex_total <= 10


@xfail_cluster(20, "class feature mechanics")
def test_c20_s06_flurry_of_blows_spends_focus_for_two_bonus_action_strikes():
    """C20-S06: SRD 5.2 ``classes24/monk/class-features/monks-focus.yml``
    (phbmnkMonksFocus), Flurry of Blows activity ``2ghJTBhilLrFn9xT`` —
    "expend 1 Focus Point to make two Unarmed Strikes as a Bonus
    Action." ``resolver.py``'s ``utility`` handling only applies
    ``effects[]`` riders; this activity's ``chatFlavor`` text carries
    no typed attack payload, and nothing represents "free follow-up
    attacks paid for by a feature use" today. Contract repair (plan R1):
    the Monk gains Monk's Focus at level 2, and the two strikes that follow
    a Flurry of Blows are Flurry strikes by engine inference (no flag).
    """

    async def _run():
        start = await start_combat(
            session_id="e2e-c20-s06",
            party=[
                PartyMemberSpec(
                    entity_id="char:monk",
                    name="Monk",
                    initiative=20,
                    hp_current=20,
                    hp_max=20,
                    class_slug="monk",
                    character_level=2,
                    dexterity=16,
                    attack_bonus=5,
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
            grid_scene=grid_scene(width=5, height=5),
            rng_seed=4,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:monk",
            intent=PlayerIntent(
                intent_type="use_feature",
                feature_id="monks-focus",
                activity_id="2ghJTBhilLrFn9xT",
            ),
        )
        assert live.custom_counters_by_entity["char:monk"]["feature_use:monks-focus"]["spent"] == 1

        for _ in range(2):
            await submit_player_intent(
                start.handle,
                actor_id="char:monk",
                intent=PlayerIntent(
                    intent_type="attack", weapon_id="unarmed-strike", target_id="mon:foe"
                ),
            )
        return live

    live = run_async(_run())
    strikes = [e for e in events_of(live, AttackRolled) if e.attacker_id == "char:monk"]
    assert len(strikes) == 2


@xfail_cluster(20, "class feature mechanics")
def test_c20_s07_action_surge_grants_a_second_action_same_turn():
    """C20-S07: SRD 5.2 ``classes24/fighter/class-features/action-surge.yml``
    — "you can take one additional action, except the Magic action."
    ``Combatant`` only carries boolean ``action_available`` today —
    there is no "additional actions granted this turn" state anywhere
    in ``orchestrator.py``; a second Attack-action swing in the same
    turn is rejected with ``IntentRejectedError("no_action_economy")``.
    Contract repair (plan R1): the surge comes first, so the one-attack
    Fighter's turn does not end after its first swing (the C14 rule that a
    one-attack actor's turn ends after its Attack action stands).
    """

    async def _run():
        start = await start_combat(
            session_id="e2e-c20-s07",
            party=[
                PartyMemberSpec(
                    entity_id="char:hero",
                    name="Hero",
                    initiative=20,
                    hp_current=20,
                    hp_max=20,
                    class_slug="fighter",
                    character_level=2,
                    attack_bonus=5,
                    strength=16,
                    equipment=("longsword",),
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
            grid_scene=grid_scene(width=5, height=5),
            rng_seed=6,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="use_feature", feature_id="action-surge"),
        )
        for _ in range(2):
            await submit_player_intent(
                start.handle,
                actor_id="char:hero",
                intent=PlayerIntent(
                    intent_type="attack", weapon_id="longsword", target_id="mon:foe"
                ),
            )
        return live

    live = run_async(_run())
    strikes = [e for e in events_of(live, AttackRolled) if e.attacker_id == "char:hero"]
    assert len(strikes) == 2


@xfail_cluster(20, "class feature mechanics")
def test_c20_s08_bardic_inspiration_die_consumed_on_later_ally_roll():
    """C20-S08: SRD 5.2 ``classes24/bard/class-features/bardic-inspiration.yml``
    — "That creature gains one of your Bardic Inspiration dice. ... Once
    within the next hour when the creature fails a D20 Test, the creature
    can roll the Bardic Inspiration die and add the number rolled to the
    d20, potentially turning the failure into a success." Nothing
    represents "bank a d6 on the TARGET, redeemable on a LATER roll" today;
    no ``attack`` intent carries a "redeem a banked die" flag. Contract
    repair (plan R1): the bard passes, so the ally attacks on its own turn
    ("Each participant in the battle takes a turn in Initiative order");
    seed 8's base attack (natural 8 + 3 = 11 against AC 14) fails, so the
    die is rolled.
    """

    def _run(*, bank: bool, redeem: bool):
        async def _inner():
            start = await start_combat(
                session_id="e2e-c20-s08",
                party=[
                    PartyMemberSpec(
                        entity_id="char:bard",
                        name="Bard",
                        initiative=20,
                        hp_current=15,
                        hp_max=15,
                        class_slug="bard",
                        character_level=3,
                        charisma=16,
                        zone_id=cell(0, 0),
                    ),
                    PartyMemberSpec(
                        entity_id="char:ally",
                        name="Ally",
                        initiative=15,
                        hp_current=15,
                        hp_max=15,
                        attack_bonus=3,
                        zone_id=cell(1, 0),
                    ),
                ],
                encounter=[
                    EncounterMemberSpec(
                        entity_id="mon:foe",
                        entity_type="Monster",
                        name="Foe",
                        initiative=1,
                        hp_current=500,
                        hp_max=500,
                        ac=14,
                        zone_id=cell(2, 0),
                    )
                ],
                scene_zones=None,
                grid_scene=grid_scene(width=5, height=5),
                rng_seed=8,
            )
            live = _get_live(start.handle)
            if bank:
                await submit_player_intent(
                    start.handle,
                    actor_id="char:bard",
                    intent=PlayerIntent(
                        intent_type="use_feature",
                        feature_id="bardic-inspiration",
                        target_id="char:ally",
                    ),
                )
            await submit_player_intent(
                start.handle, actor_id="char:bard", intent=PlayerIntent(intent_type="pass")
            )
            await submit_player_intent(
                start.handle,
                actor_id="char:ally",
                intent=PlayerIntent(
                    intent_type="attack",
                    weapon_id="longsword",
                    target_id="mon:foe",
                    redeem_granted_die="feature_grant:bardic-inspiration" if redeem else None,
                ),
            )
            return next(e for e in events_of(live, AttackRolled) if e.attacker_id == "char:ally")

        return run_async(_inner())

    run_a = _run(bank=False, redeem=False)
    run_b = _run(bank=True, redeem=True)

    delta = run_b.roll_total - run_a.roll_total
    assert 1 <= delta <= 6


@xfail_cluster(20, "class feature mechanics")
def test_c20_s09_rage_ends_at_end_of_next_turn_when_not_extended():
    """C20-S09: SRD 5.2 ``classes24/barbarian/class-features/rage.yml``
    — "The Rage lasts until the end of your next turn... you can
    extend the Rage for another round by... Make an attack roll...
    Force a saving throw... Take a Bonus Action to extend." Rage's
    ``ActiveEffect`` duration is decremented once per turn purely by
    ``_tick_durations_at_turn_end`` with no check for an extension — the
    effect survives regardless. Contract repair (plan R1): the foe's turn
    is driven between the barbarian's two turns ("Each participant in the
    battle takes a turn in Initiative order").
    """
    from dnd5e_engine.events import EffectExpired

    async def _run():
        start = await start_combat(
            session_id="e2e-c20-s09",
            party=[
                PartyMemberSpec(
                    entity_id="char:hero",
                    name="Hero",
                    initiative=20,
                    hp_current=40,
                    hp_max=40,
                    class_slug="barbarian",
                    character_level=1,
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
                    ac=20,
                    zone_id=cell(9, 9),
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
            intent=PlayerIntent(intent_type="use_feature", feature_id="rage"),
        )
        await submit_player_intent(
            start.handle, actor_id="char:hero", intent=PlayerIntent(intent_type="pass")
        )
        await advance_monster_turn(start.handle)
        await submit_player_intent(
            start.handle, actor_id="char:hero", intent=PlayerIntent(intent_type="pass")
        )
        return live

    live = run_async(_run())
    not_extended = [
        e
        for e in events_of(live, EffectExpired)
        if e.reason == "not_extended"  # API delta (C20)
    ]
    assert not_extended, "Rage should end at the end of its next turn when not extended"


@xfail_cluster(20, "class feature mechanics")
def test_c20_s10_lay_on_hands_pool_caps_at_5x_paladin_level_per_long_rest():
    """C20-S10: SRD 5.2 ``classes24/paladin/class-features/lay-on-hands.yml``
    — "restore a total number of Hit Points equal to five times your
    Paladin level." ``lay-on-hands.json``'s ``uses.max`` is the literal
    string ``"5 * @classes.paladin.levels"`` — ``_feature_use_cap``
    only resolves literal ints and ``@scale.<owner>.<key>`` tokens, so
    this formula falls through unresolved (uncapped at runtime today).
    Contract repair (plan R1): Lay on Hands is a Bonus Action and "You can
    take only one Bonus Action on your turn", so the pool is probed with
    two draws in one turn — 11 points (more than the pool holds: refused,
    no Bonus Action spent) then 10.
    """
    from dnd5e_engine.events import HealingApplied

    async def _run():
        start = await start_combat(
            session_id="e2e-c20-s10",
            party=[
                PartyMemberSpec(
                    entity_id="char:paladin",
                    name="Paladin",
                    initiative=20,
                    hp_current=30,
                    hp_max=30,
                    class_slug="paladin",
                    character_level=2,
                    zone_id=cell(0, 0),
                ),
                PartyMemberSpec(
                    entity_id="char:ally",
                    name="Ally",
                    initiative=10,
                    hp_current=1,
                    hp_max=200,
                    zone_id=cell(0, 0),
                ),
            ],
            encounter=[
                EncounterMemberSpec(
                    entity_id="mon:foe",
                    entity_type="Monster",
                    name="Foe",
                    initiative=1,
                    hp_current=50,
                    hp_max=50,
                    ac=20,
                    zone_id=cell(4, 4),
                )
            ],
            scene_zones=None,
            grid_scene=grid_scene(width=5, height=5),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        for points in (11, 10):
            await submit_player_intent(
                start.handle,
                actor_id="char:paladin",
                intent=PlayerIntent(
                    intent_type="use_feature",
                    feature_id="lay-on-hands",
                    activity_id="gXZh9aGHcywV9huC",
                    target_id="char:ally",
                    pool_points=points,  # API delta (C20): variable-amount spend
                ),
            )
        return live

    live = run_async(_run())
    total_healed = sum(
        e.amount for e in events_of(live, HealingApplied) if e.target_id == "char:ally"
    )
    assert total_healed == 10


@xfail_cluster(20, "class feature mechanics")
def test_c20_s11_cunning_action_dash_is_gated_by_feature_not_class_slug():
    """C20-S11: SRD 5.2 ``classes24/rogue/class-features/cunning-action.yml``
    — "On your turn, you can take one of the following actions as a Bonus
    Action: Dash, Disengage, or Hide." ``_handle_dash`` hardcodes
    ``class_slug != "rogue"``. Contract repair (plan R1): Cunning Action is
    a Rogue level-2 feature, so a Rogue 2's bonus-action Dash succeeds while
    a Rogue 1's and a Fighter 1's are rejected with
    ``IntentRejectedError("no_action_economy")``.
    """

    def _run(class_slug: str, level: int):
        async def _inner():
            start = await start_combat(
                session_id=f"e2e-c20-s11-{class_slug}-{level}",
                party=[
                    PartyMemberSpec(
                        entity_id="char:hero",
                        name="Hero",
                        initiative=20,
                        hp_current=20,
                        hp_max=20,
                        class_slug=class_slug,
                        character_level=level,
                        base_speed=30,
                        zone_id=cell(0, 0),
                    )
                ],
                encounter=[
                    EncounterMemberSpec(
                        entity_id="mon:foe",
                        entity_type="Monster",
                        name="Foe",
                        initiative=1,
                        hp_current=10,
                        hp_max=10,
                        ac=10,
                        zone_id=cell(9, 9),
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
                intent=PlayerIntent(intent_type="dash", use_bonus_action=True),
            )
            return live

        return run_async(_inner())

    live_rogue = _run("rogue", 2)
    from dnd5e_engine.events import DashTaken

    dashes = [e for e in events_of(live_rogue, DashTaken) if e.actor_id == "char:hero"]
    assert dashes
    assert dashes[0].budget_consumed == "bonus_action"

    with pytest.raises(IntentRejectedError):
        _run("rogue", 1)
    with pytest.raises(IntentRejectedError):
        _run("fighter", 1)
