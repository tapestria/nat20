"""C18 — monster action economy, orchestrator-level units: limited-use state
hydration and the three turn-start mechanics (legendary-action reset,
recharge rolls, regeneration). Every rule quotes the SRD 5.2 sentence it
pins. Later C18 tasks append to this file."""

from __future__ import annotations

import asyncio
from datetime import date

import pytest
from dnd5e_srd_data import MemoryAssetLoader, Provenance, ReviewState
from dnd5e_srd_data.loader import BundledAssetLoader
from dnd5e_srd_data.schema.common import CastActivity, CastSpellBlock
from dnd5e_srd_data.schema.monster import (
    AbilityScores,
    CreatureSize,
    CreatureType,
    Monster,
    MonsterAction,
    MonsterActionKind,
    Movement,
    SavingThrowProficiencies,
    Senses,
    SkillProficiencies,
)

from dnd5e_engine import (
    EncounterMemberSpec,
    GridScene,
    IntentRejectedError,
    PartyMemberSpec,
    PlayerIntent,
    advance_monster_turn,
    end_combat,
    get_live,
    resolve_legendary_resistance,
    start_combat,
    submit_player_intent,
)
from dnd5e_engine.events import (
    AttackRolled,
    ConditionApplied,
    DamageApplied,
    Death,
    HealingApplied,
    IntentSubmitted,
    LegendaryActionUsed,
    LegendaryResistanceUsed,
    RechargeRolled,
    SaveRolled,
    SpellCast,
)
from dnd5e_engine.lib_loader import set_lib_loader_for_tests
from dnd5e_engine.orchestrator import _get_live
from dnd5e_engine.spatial import cell_id as cell
from dnd5e_engine.types.conditions import ActiveCondition


def _set_condition(live, entity_id: str, condition: str) -> None:
    for idx, c in enumerate(live.initiative):
        if c.entity_id == entity_id:
            live.initiative[idx] = c.model_copy(
                update={
                    "conditions": [
                        ActiveCondition(
                            condition=condition,
                            source_entity_id="implied:scenario",
                            scope="combat",
                        )
                    ]
                }
            )
            return
    raise AssertionError(f"{entity_id} not found in initiative")


@pytest.fixture(autouse=True)
def _bundled_loader():
    set_lib_loader_for_tests(BundledAssetLoader())
    yield
    set_lib_loader_for_tests(None)


def _run(coro):
    return asyncio.run(coro)


def _events(live, kind):
    return [e for e in live.event_log if isinstance(e, kind)]


def _hero(entity_id="char:hero", *, initiative=20, hp=40, ac=15, attack_bonus=6, col=0):
    return PartyMemberSpec(
        entity_id=entity_id,
        name=entity_id,
        initiative=initiative,
        hp_current=hp,
        hp_max=hp,
        ac=ac,
        attack_bonus=attack_bonus,
        zone_id=cell(col, 0),
    )


def _foe(slug, entity_id="mon:foe", *, initiative=5, hp, hp_max=None, ac=10, col=3):
    return EncounterMemberSpec(
        entity_id=entity_id,
        entity_type="Monster",
        name=entity_id,
        initiative=initiative,
        hp_current=hp,
        hp_max=hp_max if hp_max is not None else hp,
        ac=ac,
        zone_id=cell(col, 0),
        monster_template_slug=slug,
    )


async def _start(party, encounter, *, seed=1, width=10, session="c18-units", sunlight=False):
    start = await start_combat(
        session_id=session,
        party=party,
        encounter=encounter,
        scene_zones=None,
        grid_scene=GridScene(width=width, height=10, cell_size_ft=5, sunlight=sunlight),
        rng_seed=seed,
    )
    return start.handle, _get_live(start.handle)


async def _pass(handle):
    await submit_player_intent(
        handle, actor_id="char:hero", intent=PlayerIntent(intent_type="pass")
    )


def test_regeneration_heals_at_own_turn_start_when_above_zero():
    """SRD 5.2 Regeneration: "regains [N] Hit Points at the start of each of its
    turns if it has at least 1 Hit Point." Troll heal activity: flat 10."""

    async def go():
        handle, live = await _start([_hero()], [_foe("troll", hp=40, hp_max=94, ac=15)], seed=2)
        await _pass(handle)
        await advance_monster_turn(handle)
        return live

    live = _run(go())
    heals = [e for e in _events(live, HealingApplied) if e.target_id == "mon:foe"]
    assert heals
    assert heals[0].amount == 10
    assert live.tracked_hp["mon:foe"] == 50


def test_regeneration_is_capped_at_hp_max_and_silent_at_zero():
    async def go(hp):
        handle, live = await _start(
            [_hero()], [_foe("troll", hp=max(hp, 1), hp_max=94, ac=15)], seed=2
        )
        if hp == 0:
            live.tracked_hp["mon:foe"] = 0
            live.initiative[1].hp_current = 0
        await _pass(handle)
        await advance_monster_turn(handle)
        return live

    full = _run(go(94))
    assert not [e for e in _events(full, HealingApplied) if e.target_id == "mon:foe"]
    down = _run(go(0))  # "if it has at least 1 Hit Point"
    assert not _events(down, HealingApplied)


def test_recharge_roll_only_after_the_action_was_spent():
    """SRD 5.2 Recharge X–Y: rolled at the start of each of the monster's
    turns; Foundry parity — an unspent part is not rolled for.

    C18 Task 3 note: turn 1 no longer needs a manual ``recharge_spent = True``
    flip — ``rank_monster_actions`` now ranks the available Fire Breath ahead
    of Claw, so the mephit spends it for real on turn 1 (see
    ``test_mephit_breathes_first_then_claw_or_breath_again_after_recharge``
    below for the full selection assertions). The tracked entry ends turn 2
    spent either way: on a successful roll, Fire Breath is available again
    and gets re-selected + re-spent the SAME turn; on a failed roll it just
    stays spent — either path is observed here, only the roll fields differ.
    """

    async def go():
        handle, live = await _start(
            [_hero(initiative=1)], [_foe("magma-mephit", initiative=20, hp=18, ac=11)], seed=7
        )
        uses = live.monster_action_uses_by_entity["mon:foe"]["fire-breath"]
        assert uses.recharge_spent is False
        await advance_monster_turn(handle)  # turn 1 — the mephit breathes, spending it
        assert uses.recharge_spent is True
        await _pass(handle)
        await advance_monster_turn(handle)  # turn 2 — the roll happens at turn start
        return handle, live

    handle, live = _run(go())
    rolled = _events(live, RechargeRolled)
    assert len(rolled) == 1
    ev = rolled[0]
    assert (ev.monster_id, ev.action_slug, ev.threshold) == ("mon:foe", "fire-breath", "6")
    assert 1 <= ev.roll <= 6
    assert ev.succeeded == (ev.roll >= 6)
    assert live.monster_action_uses_by_entity["mon:foe"]["fire-breath"].recharge_spent is True
    assert (
        get_live(handle).monster_action_uses_by_entity["mon:foe"]["fire-breath"].recharge_spent
        is True
    )


def test_ranked_selection_opens_with_recharge_action_then_recharges_or_repeats():
    """C18 Task 3 (S01): ``rank_monster_actions`` now ranks an available
    recharge action ahead of the first-listed offensive action, so the
    mephit opens combat with Fire Breath instead of Claw. Turn 2 rolls to
    recharge at turn start (SRD 5.2 "at the start of each of the monster's
    turns, roll 1d6 ... if within the ... range, the monster regains the
    use"); observed once for seed 7: ``roll=6`` (>= the "6" threshold, i.e.
    success), so Fire Breath is available again and re-selected the SAME
    turn. Had it failed, turn 2's action would fall back to Claw — no fire
    damage in that slice of the log — which the final assertion checks
    either way rather than hard-coding the branch not taken.
    """

    async def go():
        handle, live = await _start(
            [_hero(initiative=1)], [_foe("magma-mephit", initiative=20, hp=18, ac=11)], seed=7
        )
        await advance_monster_turn(handle)  # turn 1
        turn1_log = list(live.event_log)
        await _pass(handle)
        pre_turn2 = len(live.event_log)
        await advance_monster_turn(handle)  # turn 2
        turn2_log = live.event_log[pre_turn2:]
        return turn1_log, turn2_log

    turn1_log, turn2_log = _run(go())

    def _fire_damage_at_hero(log):
        return [
            e
            for e in log
            if isinstance(e, DamageApplied)
            and e.target_id == "char:hero"
            and e.damage_type == "fire"
        ]

    assert _fire_damage_at_hero(turn1_log), "turn 1 should open with Fire Breath, not Claw"
    turn1_intents = [
        e for e in turn1_log if isinstance(e, IntentSubmitted) and e.actor_id == "mon:foe"
    ]
    assert [i.intent_type for i in turn1_intents] == ["attack"]

    turn2_rolls = [e for e in turn2_log if isinstance(e, RechargeRolled)]
    assert len(turn2_rolls) == 1
    ev = turn2_rolls[0]
    # Pinned from a live run at seed 7 (observed, not guessed).
    assert (ev.roll, ev.succeeded) == (6, True)
    if ev.succeeded:
        assert _fire_damage_at_hero(turn2_log), "recharge succeeded — Fire Breath fires again"
    else:
        assert not _fire_damage_at_hero(turn2_log), "recharge failed — turn 2 falls back to Claw"


def test_legendary_pools_hydrate_from_the_template_and_reset_at_own_turn():
    async def go():
        handle, live = await _start(
            [_hero(initiative=25)],
            [_foe("adult-red-dragon", initiative=10, hp=256, ac=19)],
            seed=4,
        )
        dragon = live.initiative[1]
        assert (dragon.legendary_actions_max, dragon.legendary_actions_remaining) == (3, 3)
        assert dragon.legendary_resistances_max == dragon.legendary_resistances_remaining == 3
        assert get_live(handle).legendary_actions_by_entity == {"mon:foe": 3}
        dragon.legendary_actions_remaining = 1
        await _pass(handle)
        await advance_monster_turn(handle)
        return live

    live = _run(go())
    assert live.initiative[1].legendary_actions_remaining == 3


def test_template_damage_immunities_hydrate_unconditionally():
    async def go():
        _, live = await _start([_hero()], [_foe("zombie", hp=15, ac=8)])
        return live.initiative[1]

    z = _run(go())
    assert "poison" in z.damage_immunities  # verify the zombie's corpus immunities first
    assert z.physical_resistances_nonmagical_only is False


# C18 Task 5 — the mage's canonical "Spellcasting" action lists nine cast
# activities in a fixed order (At Will: Detect Magic, Light, Mage Armor, Mage
# Hand, Prestidigitation; 2/Day: Fireball, Invisibility; 1/Day: Cone of Cold,
# Fly). Fireball is the FIRST offensive one (a buff/utility spell carries no
# attack/save/damage activity of its own, so it's skipped regardless of
# uses); Cone of Cold is the next offensive one after Fireball. Foundry
# activity ids, read once from the bundled corpus while drafting this test.
_MAGE_FIREBALL_ACTIVITY_ID = "OMMdgcswZDwcu4P9"
_MAGE_INVISIBILITY_ACTIVITY_ID = "PsQU2yHchoO5kFLT"
_MAGE_CONE_OF_COLD_ACTIVITY_ID = "cDga1NaxiuzNOPlP"


def test_mage_opens_with_fireball_and_tracks_the_daily_use():
    """C18-S07 (units): hero initiative 1, mage initiative 20, seed 5 — the
    mage selects its stat-block Spellcasting action and casts Fireball (the
    first offensive activity in list order with a use remaining), at its
    printed stat-block level (4), against its own real int/PB DC (14).
    """

    async def go():
        handle, live = await _start(
            [_hero(initiative=1)], [_foe("mage", initiative=20, hp=40, ac=12)], seed=5
        )
        await advance_monster_turn(handle)
        return live

    live = _run(go())
    saves = [e for e in _events(live, SaveRolled) if e.target_id == "char:hero"]
    assert saves
    assert saves[0].ability == "dex"
    assert saves[0].dc == 14
    assert [e for e in _events(live, DamageApplied) if e.damage_type == "fire"]
    cast = _events(live, SpellCast)
    assert cast
    assert cast[0].spell_id == "fireball"
    assert cast[0].slot_level == 4
    uses = live.monster_action_uses_by_entity["mon:foe"]["spellcasting"].uses_remaining
    fireball_key = next(k for k in uses if k.endswith(f":{_MAGE_FIREBALL_ACTIVITY_ID}"))
    assert uses[fireball_key] == 1
    assert "mon:foe" not in live.spell_slots_by_entity  # no slot pool for monsters


def test_exhausted_daily_spell_falls_back_to_the_next_candidate():
    """With Fireball and Invisibility both pre-exhausted, the mage's next
    offensive candidate in list order is Cone of Cold (cold damage, a con
    save) — Fly (1/Day, after it) is a self-buff and never qualifies.
    """

    async def go():
        handle, live = await _start(
            [_hero(initiative=1)], [_foe("mage", initiative=20, hp=40, ac=12)], seed=5
        )
        uses = live.monster_action_uses_by_entity["mon:foe"]["spellcasting"].uses_remaining
        for key in list(uses):
            if key.endswith(f":{_MAGE_FIREBALL_ACTIVITY_ID}") or key.endswith(
                f":{_MAGE_INVISIBILITY_ACTIVITY_ID}"
            ):
                uses[key] = 0
        await advance_monster_turn(handle)
        return live

    live = _run(go())
    saves = [e for e in _events(live, SaveRolled) if e.target_id == "char:hero"]
    assert saves
    assert saves[0].ability == "con"
    assert [e for e in _events(live, DamageApplied) if e.damage_type == "cold"]
    cast = _events(live, SpellCast)
    assert cast
    assert cast[0].spell_id == "cone-of-cold"
    uses = live.monster_action_uses_by_entity["mon:foe"]["spellcasting"].uses_remaining
    cone_key = next(k for k in uses if k.endswith(f":{_MAGE_CONE_OF_COLD_ACTIVITY_ID}"))
    assert uses[cone_key] == 0


# -- Fix round 1 (reviewer finding) -- an attack-roll monster cast must ----
# consume Help/Vex/Sap grants exactly like a mundane monster attack does; a
# save-only cast must never touch them.

_FIRE_BOLT_UUID = "Compendium.dnd5e.spells24.Item.phbsplFireBolt00"


def _provenance() -> Provenance:
    return Provenance(
        source="foundry",
        source_url="x",
        ingest_date=date(2026, 6, 3),
        ingest_version="v1",
        srd_version=frozenset({"5.1"}),
    )


def _cast_striker_monster(slug: str = "cast-striker") -> Monster:
    """A minimal stat-block spellcaster whose ONLY action is an at-will cast
    of the bundled Fire Bolt (a ranged spell ATTACK roll cantrip) -- mirrors
    ``tests/test_orchestrator_monster_typed.py::_monster``.
    """
    return Monster(
        slug=slug,
        name="Cast Striker",
        description="A test spellcaster.",
        creature_type=CreatureType.HUMANOID,
        creature_size=CreatureSize.MEDIUM,
        hp=20,
        hp_dice="3d8+3",
        ability_scores=AbilityScores(str=10, dex=10, con=10, int=16, wis=10, cha=10),
        movement=Movement(walk=30),
        senses=Senses(),
        cr=1.0,
        proficiency_bonus=2,
        saving_throws=SavingThrowProficiencies(),
        skills=SkillProficiencies(),
        provenance=_provenance(),
        review=ReviewState(),
        spellcasting_ability="int",
        actions=[
            MonsterAction(
                slug="spellcasting",
                name="Spellcasting",
                kind=MonsterActionKind.ACTION,
                description="The creature casts a spell.",
                activities=[
                    CastActivity(
                        name="Spellcasting",
                        spell=CastSpellBlock(uuid=_FIRE_BOLT_UUID),
                    )
                ],
            )
        ],
    )


def test_attack_roll_monster_cast_consumes_a_help_grant():
    """An armed Help grant against the PC target folds "help" advantage
    into the monster's spell ATTACK roll (Fire Bolt) exactly like a mundane
    monster attack -- and, unlike the pre-fix behaviour, is CONSUMED
    afterward so it can't leak into a later, unrelated roll.

    Self-help (mon:foe grants against its own attack): keeps the
    differential clean of the UNRELATED "Help expires at the start of the
    HELPER's own next turn" sweep (SRD 5.2 Actions in Combat) -- with only
    hero + mon:foe in the encounter, the helper's own next turn never
    starts within this single ``advance_monster_turn`` call, so a survived
    grant can only mean the attack-roll consumption never ran.
    """
    fire_bolt = BundledAssetLoader().get_spell("fire-bolt")
    assert fire_bolt is not None  # verify the bundled cantrip resolves first
    set_lib_loader_for_tests(
        MemoryAssetLoader(monsters=[_cast_striker_monster()], spells=[fire_bolt])
    )

    async def go():
        handle, live = await _start(
            [_hero(initiative=1)],
            [_foe("cast-striker", initiative=20, hp=20, ac=10)],
        )
        # SRD 5.2 Actions in Combat -- Help: armed directly (no monster
        # "help" PlayerIntent path exists), mirroring
        # ``tests/test_dodge_help_hide.py``'s ``live.help_grants`` shape.
        live.help_grants["char:hero"] = ["mon:foe"]
        await advance_monster_turn(handle)
        return live

    live = _run(go())
    rolled = [
        e
        for e in _events(live, AttackRolled)
        if e.attacker_id == "mon:foe" and e.target_id == "char:hero"
    ]
    assert rolled
    assert rolled[0].advantage == "advantage"
    assert "help" in rolled[0].sources
    # The grant was CONSUMED by this attack roll -- the fix under test.
    assert live.help_grants.get("char:hero") in (None, [])


def test_save_only_monster_cast_leaves_an_armed_help_grant_untouched():
    """A save-only cast (the mage's Fireball, seed 5) never reads OR pops a
    Help grant -- Help only ever assists an ATTACK roll (SRD 5.2 Actions in
    Combat, "Assist an Attack Roll"), and an armed grant against the PC
    target must survive a same-turn save-based spell untouched.
    """

    async def go():
        handle, live = await _start(
            [_hero(initiative=1)], [_foe("mage", initiative=20, hp=40, ac=12)], seed=5
        )
        live.help_grants["char:hero"] = ["mon:foe"]
        await advance_monster_turn(handle)
        return live

    live = _run(go())
    # Fireball (a save, not an attack roll) resolved -- sanity check we're
    # actually exercising the save-only path this test claims to.
    assert [e for e in _events(live, SaveRolled) if e.target_id == "char:hero"]
    assert live.help_grants.get("char:hero") == ["mon:foe"]


# -- C18 Task 6 -- legendary actions (S02) ----------------------------------


async def _dragon_fight(seed=4):
    return await _start(
        [_hero(initiative=25, hp=60, ac=18, attack_bonus=7)],
        [_foe("adult-red-dragon", initiative=10, hp=256, ac=19, col=3)],
        seed=seed,
    )


def test_legendary_action_after_pc_turn_spends_one_use_and_keeps_the_turn_index():
    """SRD 5.2 §Legendary Actions: "immediately after another creature's
    turn" -- driving the hero's turn opens a legendary-action window for the
    dragon without touching whose turn it is."""

    async def go():
        handle, live = await _dragon_fight()
        await _pass(handle)
        idx = live.current_turn_index
        await advance_monster_turn(handle, legendary=True)
        assert live.current_turn_index == idx
        return live

    live = _run(go())
    used = _events(live, LegendaryActionUsed)
    assert used
    assert used[0].actor_id == "mon:foe"
    assert used[0].uses_remaining == 2
    assert used[0].action_slug in {"commanding-presence", "fiery-rays"}  # Pounce (utility) never
    assert live.initiative[1].legendary_actions_remaining == 2


def test_only_one_legendary_action_per_creature_turn_end():
    """SRD 5.2 §Legendary Actions: "only one of these actions can be taken
    at a time" -- a second ``legendary=True`` in the SAME window (the hero's
    turn end) is rejected even though the dragon still has uses left."""

    async def go():
        handle, _live = await _dragon_fight()
        await _pass(handle)
        await advance_monster_turn(handle, legendary=True)
        with pytest.raises(IntentRejectedError) as excinfo:
            await advance_monster_turn(handle, legendary=True)
        return excinfo.value

    err = _run(go())
    assert err.reason == "no_legendary_action"


def test_no_legendary_action_after_its_own_turn():
    """SRD 5.2 §Legendary Actions: "immediately after ANOTHER creature's
    turn" -- the dragon may not spend a legendary action right after its own
    turn ends."""

    async def go():
        handle, _live = await _dragon_fight()
        await _pass(handle)
        await advance_monster_turn(handle)  # the dragon's own driven turn
        with pytest.raises(IntentRejectedError) as excinfo:
            await advance_monster_turn(handle, legendary=True)
        return excinfo.value

    err = _run(go())
    assert err.reason == "no_legendary_action"


def test_incapacitated_dragon_cannot_take_legendary_actions():
    """SRD 5.2 Incapacitated: "can't take any action" -- applies to a
    legendary action too."""

    async def go():
        handle, live = await _dragon_fight()
        _set_condition(live, "mon:foe", "paralyzed")
        await _pass(handle)
        with pytest.raises(IntentRejectedError) as excinfo:
            await advance_monster_turn(handle, legendary=True)
        return excinfo.value

    err = _run(go())
    assert err.reason == "no_legendary_action"


def test_pool_resets_when_the_dragon_takes_its_own_turn():
    """SRD 5.2 §Legendary Actions: "regains all expended uses at the start
    of each of its turns" -- 2 left after the spend, 3 again once the dragon
    takes its own driven turn (R2)."""

    async def go():
        handle, live = await _dragon_fight()
        await _pass(handle)
        await advance_monster_turn(handle, legendary=True)
        assert live.initiative[1].legendary_actions_remaining == 2
        await advance_monster_turn(handle)  # the dragon's own driven turn
        return live

    live = _run(go())
    assert live.initiative[1].legendary_actions_remaining == 3


def test_legendary_kwarg_is_rejected_when_no_foe_has_legendary_actions():
    async def go():
        handle, _live = await _start(
            [_hero(initiative=25)], [_foe("goblin-warrior", initiative=10, hp=7, ac=15)], seed=4
        )
        await _pass(handle)
        with pytest.raises(IntentRejectedError) as excinfo:
            await advance_monster_turn(handle, legendary=True)
        return excinfo.value

    err = _run(go())
    assert err.reason == "no_legendary_action"


# -- C18 Task 7 -- Legendary Resistance (S03) --------------------------------


async def _wizard_vs_dragon(seed, *, hp=256, ac=19, slug="adult-red-dragon"):
    party = [
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
    ]
    encounter = [
        EncounterMemberSpec(
            entity_id="mon:foe",
            entity_type="Monster",
            name="Dragon",
            initiative=1,
            hp_current=hp,
            hp_max=hp,
            ac=ac,
            zone_id=cell(2, 0),
            monster_template_slug=slug,
        )
    ]
    return await _start(party, encounter, seed=seed)


async def _cast_hold_monster(handle):
    await submit_player_intent(
        handle,
        actor_id="char:wiz",
        intent=PlayerIntent(intent_type="cast_spell", spell_id="hold-monster", target_id="mon:foe"),
    )


def test_arming_requires_the_trait_and_remaining_uses():
    """R7 — arming validates the trait AND the remaining per-day pool: a
    goblin (no Legendary Resistance) is rejected outright; the dragon's 3/day
    pool arms exactly three times, then rejects a fourth."""

    async def go():
        handle, live = await _start(
            [_hero()],
            [
                _foe("goblin-warrior", entity_id="mon:goblin", hp=7, ac=15, col=3),
                _foe("adult-red-dragon", entity_id="mon:dragon", hp=256, ac=19, col=5),
            ],
            seed=1,
        )
        with pytest.raises(IntentRejectedError) as excinfo:
            resolve_legendary_resistance(handle, "mon:goblin")
        assert excinfo.value.reason == "no_legendary_resistance"

        assert resolve_legendary_resistance(handle, "mon:dragon") == 1
        assert resolve_legendary_resistance(handle, "mon:dragon") == 2
        assert resolve_legendary_resistance(handle, "mon:dragon") == 3
        with pytest.raises(IntentRejectedError) as excinfo2:
            resolve_legendary_resistance(handle, "mon:dragon")
        assert excinfo2.value.reason == "no_legendary_resistance"
        return live

    _run(go())


def test_armed_dragon_converts_the_next_failed_save_and_skips_the_condition():
    """SRD 5.2 Legendary Resistance: "If the monster fails a saving throw,
    it can choose to succeed instead." Catalog S03 fixture, seed 2 (natural
    2 vs Hold Monster's DC): an ARMED dragon converts the failure — the
    emitted ``SaveRolled`` already carries ``succeeded=True``, no Paralyzed
    condition applies, and ``LegendaryResistanceUsed`` follows it."""

    async def go():
        handle, live = await _wizard_vs_dragon(seed=2)
        assert resolve_legendary_resistance(handle, "mon:foe") == 1
        await _cast_hold_monster(handle)
        return live

    live = _run(go())
    save = next(e for e in _events(live, SaveRolled) if e.target_id == "mon:foe")
    assert save.succeeded is True
    assert save.natural == 2
    used = _events(live, LegendaryResistanceUsed)
    assert used
    assert used[0].actor_id == "mon:foe"
    assert used[0].uses_remaining == 2
    assert not [e for e in _events(live, ConditionApplied) if e.condition == "paralyzed"]
    assert live.event_log.index(save) < live.event_log.index(used[0])


def test_unarmed_dragon_is_unchanged():
    """Same seed-2 fixture, no arming: the failure applies Paralyzed exactly
    as before this feature, no ``LegendaryResistanceUsed`` fires, and the
    pool stays untouched."""

    async def go():
        handle, live = await _wizard_vs_dragon(seed=2)
        await _cast_hold_monster(handle)
        return handle, live

    handle, live = _run(go())
    save = next(e for e in _events(live, SaveRolled) if e.target_id == "mon:foe")
    assert save.succeeded is False
    assert [e for e in _events(live, ConditionApplied) if e.condition == "paralyzed"]
    assert not _events(live, LegendaryResistanceUsed)
    assert get_live(handle).legendary_resistances_by_entity["mon:foe"] == 3


def test_armed_use_is_kept_for_a_successful_save():
    """SRD 5.2 Legendary Resistance only triggers on a FAILURE — seed 9's
    save succeeds on its own, so the armed declaration is neither consumed
    nor does it emit ``LegendaryResistanceUsed``."""

    async def go():
        handle, live = await _wizard_vs_dragon(seed=9)
        assert resolve_legendary_resistance(handle, "mon:foe") == 1
        await _cast_hold_monster(handle)
        return handle, live

    handle, live = _run(go())
    save = next(e for e in _events(live, SaveRolled) if e.target_id == "mon:foe")
    assert save.succeeded is True
    assert not _events(live, LegendaryResistanceUsed)
    assert get_live(handle).legendary_resistances_by_entity["mon:foe"] == 3
    assert _get_live(handle).legendary_resistance_armed.get("mon:foe") == 1


def test_repeat_save_path_honours_an_armed_use():
    """SRD §Hold Monster's end-of-turn repeat save bypasses the typed
    activity resolver entirely (``_run_end_of_turn_saves`` rolls its own
    d20) — the orchestrator-level ``_consume_armed_legendary_resistance`` helper
    must honour an armed declaration there too."""

    async def go():
        handle, live = await _wizard_vs_dragon(seed=2)
        await _cast_hold_monster(handle)  # unarmed: seed 2 fails -> Paralyzed
        assert resolve_legendary_resistance(handle, "mon:foe") == 1
        pre_event_count = len(live.event_log)
        await advance_monster_turn(handle)  # the dragon's own turn ends here
        return live, pre_event_count

    live, pre_event_count = _run(go())
    tail = live.event_log[pre_event_count:]
    repeat_saves = [e for e in tail if isinstance(e, SaveRolled)]
    assert repeat_saves, "expected the end-of-turn repeat save to fire"
    assert repeat_saves[0].succeeded is True
    used = [e for e in tail if isinstance(e, LegendaryResistanceUsed)]
    assert used
    assert used[0].uses_remaining == 2


# -- C18 Task 7 fix round 1 -- Grapple/Shove bypass + double-decrement -------


def test_grapple_of_an_armed_dragon_converts_the_failed_save():
    """Fix round 1, Finding 1 — ``_roll_unarmed_option_save`` (Grapple/Shove)
    bypasses ``activities/save_primitive.roll_save`` entirely, just like the
    repeat save and the concentration check; an armed dragon must not be
    Grappled on a save that would otherwise fail, and the spent use must not
    leak into a later save."""

    async def go():
        handle, live = await _start(
            [_hero(col=0)],
            [_foe("adult-red-dragon", hp=256, ac=19, col=1)],
            seed=1,
        )
        # STR 1 / DEX 1 guarantees the save fails regardless of the d20
        # (mirrors the C14 grapple-save-fail idiom — this path has no
        # ``force_save_d20`` seam).
        for idx, c in enumerate(live.initiative):
            if c.entity_id == "mon:foe":
                live.initiative[idx] = c.model_copy(update={"strength": 1, "dexterity": 1})
                break
        assert resolve_legendary_resistance(handle, "mon:foe") == 1
        await submit_player_intent(
            handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="grapple", target_id="mon:foe"),
        )
        return handle, live

    handle, live = _run(go())
    save = next(e for e in _events(live, SaveRolled) if e.target_id == "mon:foe")
    assert save.succeeded is True
    used = _events(live, LegendaryResistanceUsed)
    assert used
    assert used[0].uses_remaining == 2
    assert not [e for e in _events(live, ConditionApplied) if e.condition == "grappled"]
    assert _get_live(handle).legendary_resistance_armed.get("mon:foe", 0) == 0


def test_concentration_check_double_decrement_is_prevented_with_two_armed_uses():
    """Fix round 1, Finding 2 — ``_consume_armed_legendary_resistance`` fires from
    INSIDE ``resolve_activity`` (via ``_emit_apply_damage``) on the
    concentration-check path, so its ``LegendaryResistanceUsed`` lands inside
    the very ``[pre_event_count, ...)`` window an enclosing
    ``_sync_legendary_resistance`` call scans afterward. With TWO armed uses
    the (pre-fix) bug silently drops one for free; the single-authoritative-
    writer fix must leave exactly one use spent per failed check."""

    async def go():
        handle, live = await _wizard_vs_dragon(seed=1)
        assert resolve_legendary_resistance(handle, "mon:foe") == 1
        assert resolve_legendary_resistance(handle, "mon:foe") == 2
        dragon = next(c for c in live.initiative if c.entity_id == "mon:foe")
        # CON 1 + no save proficiency guarantees the concentration CON save
        # fails against a massive-damage DC (capped at 30) regardless of the
        # seeded roll (this path has no ``force_save_d20`` seam either).
        dragon.constitution = 1
        dragon.save_proficiencies = []
        return handle, live

    handle, live = _run(go())

    from dnd5e_engine import orchestrator as orch

    def _fail_a_concentration_check() -> list[LegendaryResistanceUsed]:
        live.concentration_chain["mon:foe"] = [("mon:foe", "eff:test", "spell:test")]
        pre = len(live.event_log)
        orch._emit_apply_damage(
            live,
            orch.DamageApplied(
                target_id="mon:foe",
                amount=1000,
                damage_type="fire",
                source_id="char:wiz",
                is_overkill=False,
            ),
        )
        # Mirrors the enclosing resolution's own post-``resolve_activity``
        # call — the exact window Finding 2 identified as re-processing the
        # helper's own event.
        orch._sync_legendary_resistance(live, pre)
        return [e for e in live.event_log[pre:] if isinstance(e, LegendaryResistanceUsed)]

    first = _fail_a_concentration_check()
    assert first
    assert first[0].uses_remaining == 2
    assert _get_live(handle).legendary_resistance_armed.get("mon:foe") == 1
    dragon = next(c for c in live.initiative if c.entity_id == "mon:foe")
    assert dragon.legendary_resistances_remaining == 2

    second = _fail_a_concentration_check()
    assert second
    assert second[0].uses_remaining == 1
    assert _get_live(handle).legendary_resistance_armed.get("mon:foe", 0) == 0
    dragon = next(c for c in live.initiative if c.entity_id == "mon:foe")
    assert dragon.legendary_resistances_remaining == 1


def test_dead_dragon_cannot_take_legendary_actions():
    """A dragon at 0 HP is no longer a legal legendary actor — SRD 5.2
    legendary actions are a living creature's option, not a corpse's."""

    async def go():
        handle, live = await _dragon_fight()
        await _pass(handle)
        live.initiative[1].hp_current = 0
        live.initiative[1].is_alive = False
        with pytest.raises(IntentRejectedError) as excinfo:
            await advance_monster_turn(handle, legendary=True)
        return excinfo.value

    err = _run(go())
    assert err.reason == "no_legendary_action"


def test_pack_tactics_ignores_an_incapacitated_ally():
    """R8 — SRD 5.2 stat-block trait "Pack Tactics": "if at least one of the
    [monster]'s allies is within 5 feet of the creature and the ally
    doesn't have the Incapacitated condition." Mirrors the S06 e2e fixture
    (mon:wolf1 adjacent to char:hero at (5,5); mon:wolf2 also adjacent at
    (6,6)) but PARALYZES wolf2 (implies Incapacitated) — the only nearby
    ally no longer qualifies, so wolf1's attack stays at normal."""

    async def go():
        hero = PartyMemberSpec(
            entity_id="char:hero",
            name="Hero",
            initiative=20,
            hp_current=30,
            hp_max=30,
            ac=14,
            zone_id=cell(5, 5),
        )
        wolf1 = EncounterMemberSpec(
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
        handle, live = await _start([hero], [wolf1, wolf2], seed=3)
        _set_condition(live, "mon:wolf2", "paralyzed")
        await _pass(handle)
        await advance_monster_turn(handle)  # mon:wolf1 attacks char:hero
        return live

    live = _run(go())
    rolled = next(e for e in _events(live, AttackRolled) if e.attacker_id == "mon:wolf1")
    assert rolled.advantage == "normal"


def _zombie_encounter():
    return [
        EncounterMemberSpec(
            entity_id="mon:zombie",
            entity_type="Monster",
            name="Zombie",
            initiative=1,
            hp_current=1,
            hp_max=22,
            ac=1,
            zone_id=cell(1, 0),
            monster_template_slug="zombie",
        )
    ]


async def _undead_fortitude_fight(*, constitution: int):
    """A real ``zombie`` (SRD 5.2 Undead Fortitude) at 1 HP, AC 1 (guaranteed
    hit), struck by a longsword-armed hero. Seed 1's longsword swing hits,
    is not a Critical Hit, deals 2 slashing (neither Radiant nor a crit, so
    the trait always triggers), and rolls a CON save total of 24 — high
    enough to clear DC 7 (5 + 2) with room to spare at ``constitution=40``
    (+15 mod), and low enough to fail the SAME DC at ``constitution=1``
    (-5 mod, roll total 4). Mirrors ``dragon.constitution = 1`` elsewhere in
    this file — mutating the hydrated ``Combatant`` directly is this file's
    established seam for forcing a save outcome (no ``force_save_d20`` exists
    for this trait's roll — R8 deliberately keeps it a single plain draw)."""
    handle, live = await _start([_hero()], _zombie_encounter(), seed=1)
    zombie = next(c for c in live.initiative if c.entity_id == "mon:zombie")
    zombie.constitution = constitution
    zombie.save_proficiencies = []
    await submit_player_intent(
        handle,
        actor_id="char:hero",
        intent=PlayerIntent(intent_type="attack", weapon_id="longsword", target_id="mon:zombie"),
    )
    return handle, live


def test_undead_fortitude_saves_the_zombie_at_one_hp_on_the_live_path():
    """Fix round 1 — SRD 5.2 stat-block trait "Undead Fortitude" through the
    REAL ``start_combat``/``submit_player_intent`` loop (not just the pure
    ``apply_damage`` harness): a successful save must leave the bearer ALIVE
    at 1 HP, with no ``Death`` event and not in ``dead_ids`` — the exact bug
    the reviewer's finding pinned (``_emit_apply_damage`` independently
    recomputing HP from ``tracked_hp`` and the event's full, unmodified
    ``amount``, then unconditionally firing ``Death`` at ≤0)."""
    live = _run(_undead_fortitude_fight(constitution=40))[1]

    save = next(e for e in _events(live, SaveRolled) if e.target_id == "mon:zombie")
    assert save.succeeded is True
    assert save.dc == 7  # 5 + the 2 damage dealt

    damage = next(e for e in _events(live, DamageApplied) if e.target_id == "mon:zombie")
    assert damage.amount == 2  # R8: the event still reports the FULL amount
    assert damage.is_overkill is False

    assert not _events(live, Death)
    assert "mon:zombie" not in live.dead_ids
    assert live.tracked_hp["mon:zombie"] == 1
    zombie = next(c for c in live.initiative if c.entity_id == "mon:zombie")
    assert zombie.hp_current == 1
    assert zombie.is_alive is True


def test_undead_fortitude_failed_save_kills_the_zombie_on_the_live_path():
    """The failing-save counterpart (so the round-1 fix cannot pass by simply
    never killing anything): with the save guaranteed to fail, behavior is
    UNCHANGED from before this fix — the zombie drops to 0 HP and dies."""
    live = _run(_undead_fortitude_fight(constitution=1))[1]

    save = next(e for e in _events(live, SaveRolled) if e.target_id == "mon:zombie")
    assert save.succeeded is False
    assert save.dc == 7

    damage = next(e for e in _events(live, DamageApplied) if e.target_id == "mon:zombie")
    assert damage.amount == 2
    assert damage.is_overkill is True

    deaths = _events(live, Death)
    assert len(deaths) == 1
    assert deaths[0].target_id == "mon:zombie"
    assert "mon:zombie" in live.dead_ids
    assert live.tracked_hp["mon:zombie"] == 0


def test_fleeing_goblin_sets_has_fled_and_combat_ends_with_flee():
    """R9: the flee-stance branch of ``advance_monster_turn`` persists
    ``Combatant.has_fled = True`` (AGGRESSIVE goblin below the 10% HP
    threshold), and ``_derive_ended_reason`` reports ``"flee"`` once every
    living foe carries that flag."""

    async def go():
        handle, live = await _start(
            [_hero()], [_foe("goblin-warrior", hp=1, hp_max=20, ac=13)], seed=1
        )
        await _pass(handle)
        await advance_monster_turn(handle)
        current = next(c for c in live.initiative if c.entity_id == "mon:foe")
        assert current.has_fled is True
        return await end_combat(handle)

    result = _run(go())
    assert result.outcome.ended_reason == "flee"


def test_flee_requires_every_living_foe_to_have_fled():
    """R9: ``"flee"`` requires EVERY living foe to have fled — a second,
    full-HP goblin that never fled means the encounter is still contested,
    so ``_derive_ended_reason`` falls through to ``"forced"``."""

    async def go():
        handle, _live = await _start(
            [_hero()],
            [
                _foe(
                    "goblin-warrior",
                    entity_id="mon:foe1",
                    hp=1,
                    hp_max=20,
                    ac=13,
                    col=3,
                    initiative=10,
                ),
                _foe(
                    "goblin-warrior",
                    entity_id="mon:foe2",
                    hp=20,
                    hp_max=20,
                    ac=13,
                    col=4,
                    initiative=5,
                ),
            ],
            seed=1,
        )
        await _pass(handle)
        await advance_monster_turn(handle)  # foe1: below threshold, flees
        await advance_monster_turn(handle)  # foe2: full HP, still fighting
        return await end_combat(handle)

    result = _run(go())
    assert result.outcome.ended_reason == "forced"


def test_dead_foes_do_not_block_flee():
    """R9: ``living_foes`` excludes ``live.dead_ids`` — a dead ally never
    blocks a ``"flee"`` verdict for the survivor that fled, and when EVERY
    foe is dead the pre-existing ``"victory"`` branch still wins (empty
    ``living_foes`` never satisfies the new all-fled check)."""

    async def go(*, kill_first_too):
        handle, live = await _start(
            [_hero()],
            [
                _foe(
                    "goblin-warrior",
                    entity_id="mon:foe1",
                    hp=1,
                    hp_max=20,
                    ac=13,
                    col=3,
                    initiative=10,
                ),
                _foe(
                    "goblin-warrior",
                    entity_id="mon:foe2",
                    hp=1,
                    hp_max=20,
                    ac=13,
                    col=4,
                    initiative=5,
                ),
            ],
            seed=1,
        )
        await _pass(handle)
        await advance_monster_turn(handle)  # foe1: below threshold, flees
        live.dead_ids.add("mon:foe2")
        if kill_first_too:
            live.dead_ids.add("mon:foe1")
        return await end_combat(handle)

    one_dead_one_fled = _run(go(kill_first_too=False))
    assert one_dead_one_fled.outcome.ended_reason == "flee"

    all_dead = _run(go(kill_first_too=True))
    assert all_dead.outcome.ended_reason == "victory"


def test_flag_clears_when_the_monster_fights_again():
    """R9: healing a fled monster back above the flee threshold and driving
    its turn again resets ``has_fled`` to False — the flag reflects current
    stance, not the fact it once fled."""

    async def go():
        handle, live = await _start(
            [_hero()], [_foe("goblin-warrior", hp=1, hp_max=20, ac=13)], seed=1
        )
        await _pass(handle)
        await advance_monster_turn(handle)
        fled = next(c for c in live.initiative if c.entity_id == "mon:foe")
        assert fled.has_fled is True

        await _pass(handle)
        live.tracked_hp["mon:foe"] = 15
        for idx, c in enumerate(live.initiative):
            if c.entity_id == "mon:foe":
                live.initiative[idx] = c.model_copy(update={"hp_current": 15})
                break
        await advance_monster_turn(handle)
        return next(c for c in live.initiative if c.entity_id == "mon:foe")

    current = _run(go())
    assert current.has_fled is False


# -- C18 final review fix wave -----------------------------------------------
# Finding 1: ``LegendaryResistanceUsed`` fires AFTER the ``SaveRolled`` (and,
# on the concentration path, the ``ConcentrationCheck``) it converts, on every
# orchestrator-level save path — the event's own documented contract.


def test_grapple_conversion_emits_legendary_resistance_used_after_save_rolled():
    async def go():
        handle, live = await _start(
            [_hero(col=0)],
            [_foe("adult-red-dragon", hp=256, ac=19, col=1)],
            seed=1,
        )
        for idx, c in enumerate(live.initiative):
            if c.entity_id == "mon:foe":
                live.initiative[idx] = c.model_copy(update={"strength": 1, "dexterity": 1})
                break
        assert resolve_legendary_resistance(handle, "mon:foe") == 1
        await submit_player_intent(
            handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="grapple", target_id="mon:foe"),
        )
        return live

    live = _run(go())
    save = next(e for e in _events(live, SaveRolled) if e.target_id == "mon:foe")
    used = _events(live, LegendaryResistanceUsed)
    assert len(used) == 1
    assert save.succeeded is True
    assert live.event_log.index(save) < live.event_log.index(used[0])
    dragon = next(c for c in live.initiative if c.entity_id == "mon:foe")
    assert dragon.legendary_resistances_remaining == 2


def test_concentration_conversion_emits_legendary_resistance_used_after_both_checks():
    async def go():
        handle, live = await _wizard_vs_dragon(seed=1)
        assert resolve_legendary_resistance(handle, "mon:foe") == 1
        dragon = next(c for c in live.initiative if c.entity_id == "mon:foe")
        dragon.constitution = 1
        dragon.save_proficiencies = []
        return live

    live = _run(go())
    from dnd5e_engine import orchestrator as orch
    from dnd5e_engine.events import ConcentrationCheck

    live.concentration_chain["mon:foe"] = [("mon:foe", "eff:test", "spell:test")]
    pre = len(live.event_log)
    orch._emit_apply_damage(
        live,
        orch.DamageApplied(
            target_id="mon:foe",
            amount=1000,
            damage_type="fire",
            source_id="char:wiz",
            is_overkill=False,
        ),
    )
    orch._sync_legendary_resistance(live, pre)
    tail = live.event_log[pre:]
    kinds = [
        type(e).__name__
        for e in tail
        if isinstance(e, (SaveRolled, ConcentrationCheck, LegendaryResistanceUsed))
    ]
    assert kinds == ["SaveRolled", "ConcentrationCheck", "LegendaryResistanceUsed"]
    check = next(e for e in tail if isinstance(e, ConcentrationCheck))
    assert check.succeeded is True
    dragon = next(c for c in live.initiative if c.entity_id == "mon:foe")
    assert dragon.legendary_resistances_remaining == 2


def test_repeat_save_conversion_emits_legendary_resistance_used_after_save_rolled():
    async def go():
        handle, live = await _wizard_vs_dragon(seed=2)
        await _cast_hold_monster(handle)  # unarmed: seed 2 fails -> Paralyzed
        assert resolve_legendary_resistance(handle, "mon:foe") == 1
        pre_event_count = len(live.event_log)
        await advance_monster_turn(handle)
        return live, pre_event_count

    live, pre_event_count = _run(go())
    tail = live.event_log[pre_event_count:]
    save = next(e for e in tail if isinstance(e, SaveRolled) and e.target_id == "mon:foe")
    used = [e for e in tail if isinstance(e, LegendaryResistanceUsed)]
    assert len(used) == 1
    assert save.succeeded is True
    assert tail.index(save) < tail.index(used[0])


def test_sync_legendary_resistance_is_idempotent_over_overlapping_windows():
    """Finding 10: re-scanning a window that already holds a processed
    ``LegendaryResistanceUsed`` (a nested resolution's window overlapping an
    outer one) must not decrement the armed count a second time."""

    async def go():
        handle, live = await _wizard_vs_dragon(seed=2)
        assert resolve_legendary_resistance(handle, "mon:foe") == 1
        assert resolve_legendary_resistance(handle, "mon:foe") == 2
        await _cast_hold_monster(handle)
        return live

    live = _run(go())
    from dnd5e_engine import orchestrator as orch

    assert len(_events(live, LegendaryResistanceUsed)) == 1
    assert live.legendary_resistance_armed.get("mon:foe") == 1
    orch._sync_legendary_resistance(live, 0)
    orch._sync_legendary_resistance(live, 0)
    assert live.legendary_resistance_armed.get("mon:foe") == 1
    dragon = next(c for c in live.initiative if c.entity_id == "mon:foe")
    assert dragon.legendary_resistances_remaining == 2


# Finding 3: a dead monster has no turn start — no recharge roll, no draw.


def test_dead_mephit_does_not_roll_recharge_when_its_turn_comes_round():
    async def go():
        handle, live = await _start(
            [_hero(initiative=1)], [_foe("magma-mephit", initiative=20, hp=18, ac=11)], seed=7
        )
        await advance_monster_turn(handle)  # turn 1 — Fire Breath, now spent
        assert live.monster_action_uses_by_entity["mon:foe"]["fire-breath"].recharge_spent
        await _pass(handle)
        # The mephit dies before its turn 2 comes round.
        live.tracked_hp["mon:foe"] = 0
        for c in live.initiative:
            if c.entity_id == "mon:foe":
                c.hp_current = 0
                c.is_alive = False
        live.dead_ids.add("mon:foe")
        rng_state = live.rng.getstate()
        pre = len(live.event_log)
        await advance_monster_turn(handle)
        return live, pre, rng_state

    live, pre, rng_state = _run(go())
    tail = live.event_log[pre:]
    assert not [e for e in tail if isinstance(e, RechargeRolled)]
    assert live.rng.getstate() == rng_state
    assert [e.intent_type for e in tail if isinstance(e, IntentSubmitted)] == ["pass"]


# Finding 4: the Spellcasting action ranks in the limited-use tier only while
# a limited-use cast has a use remaining, and the cast candidate prefers that
# limited-use cast over an at-will one. SRD 5.2 Multiattack DM guidance: "have
# it use Multiattack on any of its turns in which it's not using one of its
# more powerful abilities."


def test_adult_red_dragon_breathes_casts_fireball_once_then_multiattacks():
    """The adult red dragon's Spellcasting lists Command and Scorching Ray at
    will and Fireball 1/Day. Each main turn it takes the most powerful option
    it has: Fire Breath when charged; else its 1/Day Fireball while unused;
    else Multiattack (Rend) — never an at-will Command over Rend."""

    async def go(seed):
        handle, live = await _start(
            [_hero(initiative=25, hp=900, ac=18)],
            [_foe("adult-red-dragon", initiative=10, hp=256, ac=19, col=1)],
            seed=seed,
        )
        turns = []
        for _ in range(5):
            await _pass(handle)
            pre = len(live.event_log)
            await advance_monster_turn(handle)
            turns.append(live.event_log[pre:])
        return turns

    turns = _run(go(4))
    breath_charged = True
    fireball_used = False
    kinds = []
    for tail in turns:
        for e in tail:
            if isinstance(e, RechargeRolled) and e.succeeded:
                breath_charged = True
        spells = [e.spell_id for e in tail if isinstance(e, SpellCast)]
        attacks = [e for e in tail if isinstance(e, AttackRolled) and e.attacker_id == "mon:foe"]
        assert "command" not in spells
        if breath_charged:
            assert spells == [], "a charged breath is used first"
            assert attacks == []
            kinds.append("breath")
            breath_charged = False
        elif not fireball_used:
            assert spells == ["fireball"]
            kinds.append("fireball")
            fireball_used = True
        else:
            assert spells == []
            assert attacks, "breath spent + Fireball used -> Multiattack"
            kinds.append("multiattack")
    # Pinned from a live run at seed 4 (observed, not guessed).
    assert kinds.count("fireball") == 1
    assert "multiattack" in kinds
    assert kinds[:2] == ["breath", "fireball"]


# Finding 8: a monster's spell attack rolls with PB + its spellcasting
# ability modifier (the stat block's own "+N to hit with spell attacks"),
# not its weapon ``attack_bonus``.


def test_monster_spell_attack_uses_pb_plus_spellcasting_modifier():
    """Cast-striker: INT 16 (+3), PB +2 -> +5 to hit with Fire Bolt, even
    though the host set its weapon ``attack_bonus`` to +9 (the adult red
    dragon's stat block pairs +14 Rend with "+12 to hit with spell
    attacks" — the same split)."""
    fire_bolt = BundledAssetLoader().get_spell("fire-bolt")
    assert fire_bolt is not None
    set_lib_loader_for_tests(
        MemoryAssetLoader(monsters=[_cast_striker_monster()], spells=[fire_bolt])
    )

    async def go():
        spec = _foe("cast-striker", initiative=20, hp=20, ac=10).model_copy(
            update={"attack_bonus": 9}
        )
        handle, live = await _start([_hero(initiative=1)], [spec])
        await advance_monster_turn(handle)
        return live

    live = _run(go())
    rolled = [e for e in _events(live, AttackRolled) if e.attacker_id == "mon:foe"]
    assert rolled
    assert rolled[0].modifier == 5
    assert rolled[0].roll_total == rolled[0].natural + 5
