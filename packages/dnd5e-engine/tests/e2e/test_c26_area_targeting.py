"""C26 — area targeting.

Transcribed from the local C26 scenario catalog (S01–S16). Every setup is a
12x12 ``GridScene`` at ``rng_seed=1`` unless the scenario names another seed or
grid; positions are ``cell(col, row)``. SRD 5.2 §Areas of Effect: "Each
creature of your choice in a 5-foot-radius Sphere" (Sleep); "If a spell targets
a creature of your choice, you can choose yourself"; monster stat blocks name
"which creatures make the save" ("each creature in a 60-foot Cone", "each enemy
in a 20-foot-radius Sphere").

S01–S04 and S09 are the monster side of area targeting and stay strict-xfail
until the monster-aiming cluster lands.
"""

from __future__ import annotations

from typing import Any

from dnd5e_srd_data.loader import BundledAssetLoader

from dnd5e_engine import PlayerIntent
from dnd5e_engine.events import (
    ActorMoved,
    AttackRolled,
    CastFailed,
    DamageApplied,
    IntentSubmitted,
    RechargeRolled,
    SaveRolled,
    SpellCast,
)
from dnd5e_engine.orchestrator import (
    _get_live,
    advance_monster_turn,
    start_combat,
    submit_player_intent,
)
from dnd5e_engine.specs import EncounterMemberSpec, GridScene, PartyMemberSpec
from tests.e2e.harness import cell, events_of, grid_scene, run_async, xfail_cluster

_MONSTER_AIMING = xfail_cluster(26, "area targeting: monster aiming")
_ACTOR_SIDE = xfail_cluster(26, "area targeting: the actor's side")


def _pc(entity_id: str, at: str, **fields: Any) -> PartyMemberSpec:
    """A 30-HP, AC 12 character that acts first."""
    base: dict[str, Any] = {
        "entity_id": entity_id,
        "name": entity_id.removeprefix("char:").title(),
        "initiative": 20,
        "hp_current": 30,
        "hp_max": 30,
        "ac": 12,
        "zone_id": at,
    }
    return PartyMemberSpec(**(base | fields))


def _sturdy(entity_id: str, at: str, initiative: int) -> PartyMemberSpec:
    """A 200-HP character, so a monster's area drops nobody mid-scenario."""
    return _pc(entity_id, at, initiative=initiative, hp_current=200, hp_max=200)


def _wizard(at: str, spells: list[str], slots: dict[int, int], **fields: Any) -> PartyMemberSpec:
    """``char:wiz``: a level-17 Wizard, INT 18, with ``spells`` and ``slots``."""
    return _pc(
        "char:wiz",
        at,
        class_slug="wizard",
        character_level=17,
        intelligence=18,
        spells_known=spells,
        spell_slots=slots,
        **fields,
    )


def _foe(
    entity_id: str, at: str, slug: str = "goblin-warrior", **fields: Any
) -> EncounterMemberSpec:
    """A template monster (``slug``) that acts after the party: 30 HP, AC 12."""
    base: dict[str, Any] = {
        "entity_id": entity_id,
        "entity_type": "Monster",
        "name": entity_id.removeprefix("mon:").title(),
        "initiative": 5,
        "hp_current": 30,
        "hp_max": 30,
        "ac": 12,
        "monster_template_slug": slug,
        "zone_id": at,
    }
    return EncounterMemberSpec(**(base | fields))


def _start(
    party: list[PartyMemberSpec],
    encounter: list[EncounterMemberSpec],
    *,
    session: str,
    seed: int = 1,
    grid: GridScene | None = None,
):
    async def _inner():
        start = await start_combat(
            session_id=session,
            party=party,
            encounter=encounter,
            grid_scene=grid or grid_scene(12, 12),
            rng_seed=seed,
        )
        return start.handle, _get_live(start.handle)

    return run_async(_inner())


def _act(handle, actor_id: str, **intent: Any) -> None:
    run_async(submit_player_intent(handle, actor_id=actor_id, intent=PlayerIntent(**intent)))


def _monster_turn(handle) -> None:
    run_async(advance_monster_turn(handle))


def _saved(live) -> list[str]:
    """Who rolled a save, in event order."""
    return [e.target_id for e in events_of(live, SaveRolled)]


def _areas(live) -> list[Any]:
    """The ``AreaTargeted`` events, read by type so the module imports before
    the event exists."""
    return [e for e in live.event_log if e.type == "area_targeted"]


def _combatant(live, entity_id: str):
    return next(c for c in live.initiative if c.entity_id == entity_id)


# ── monster side (strict-xfail until monster aiming) ─────────────────────────


@_MONSTER_AIMING
def test_c26_s01_a_breath_hits_everyone_in_the_cone() -> None:
    dragon = _foe("mon:dragon", cell(5, 5), "adult-red-dragon", initiative=20, hp_current=256)
    party = [
        _sturdy("char:a", cell(5, 7), 10),
        _sturdy("char:b", cell(6, 8), 9),
        _sturdy("char:c", cell(4, 8), 8),
        _sturdy("char:far", cell(0, 0), 7),
    ]
    handle, live = _start(party, [dragon], session="e2e-c26-s01")
    _monster_turn(handle)
    saves = events_of(live, SaveRolled)
    assert {e.target_id for e in saves} == {"char:a", "char:b", "char:c"}
    assert {e.ability for e in saves} == {"dex"}
    damage = {e.target_id: e.amount for e in events_of(live, DamageApplied)}
    full = max(damage.values())
    for save in saves:
        assert damage[save.target_id] == (full // 2 if save.succeeded else full)
    [area] = _areas(live)
    assert (area.shape, area.size_ft, area.origin, area.direction) == (
        "cone",
        60,
        cell(5, 5),
        (0, 1),
    )
    assert set(area.affected_ids) == {"char:a", "char:b", "char:c"}


@_MONSTER_AIMING
def test_c26_s02_the_ai_breathes_away_from_its_ally() -> None:
    dragon = _foe("mon:dragon", cell(5, 5), "adult-red-dragon", initiative=20, hp_current=256)
    kobold = _foe("mon:kobold", cell(6, 7), "kobold-warrior", initiative=1)
    party = [
        _sturdy("char:n1", cell(5, 3), 10),
        _sturdy("char:n2", cell(6, 2), 9),
        _sturdy("char:s1", cell(5, 7), 8),
        _sturdy("char:s2", cell(4, 8), 7),
    ]
    handle, live = _start(party, [dragon, kobold], session="e2e-c26-s02")
    _monster_turn(handle)
    assert set(_saved(live)) == {"char:n1", "char:n2"}
    assert "mon:kobold" not in {e.target_id for e in events_of(live, DamageApplied)}
    [area] = _areas(live)
    assert area.direction == (0, -1)


@_MONSTER_AIMING
def test_c26_s03_no_enemy_in_reach_means_no_breath() -> None:
    dragon = _foe("mon:dragon", cell(0, 5), "adult-red-dragon", initiative=20, hp_current=256)
    party = [_sturdy("char:a", cell(25, 5), 10), _sturdy("char:b", cell(25, 6), 9)]
    handle, live = _start(party, [dragon], session="e2e-c26-s03", grid=grid_scene(30, 12))
    _monster_turn(handle)
    assert events_of(live, SaveRolled) == []
    assert [e for e in events_of(live, ActorMoved) if e.actor_id == "mon:dragon"]
    _act(handle, "char:a", intent_type="pass")
    _act(handle, "char:b", intent_type="pass")
    _monster_turn(handle)
    assert [e for e in events_of(live, RechargeRolled) if e.action_slug == "fire-breath"] == []


@_MONSTER_AIMING
def test_c26_s04_a_monster_fireball_catches_the_cluster() -> None:
    mage = _foe("mon:mage", cell(0, 5), "mage", initiative=20, hp_current=81)
    party = [
        _sturdy("char:a", cell(8, 5), 10),
        _sturdy("char:b", cell(9, 6), 9),
        _sturdy("char:c", cell(10, 4), 8),
    ]
    handle, live = _start(party, [mage], session="e2e-c26-s04")
    _monster_turn(handle)
    [cast] = events_of(live, SpellCast)
    assert (cast.spell_id, cast.slot_level) == ("fireball", 4)
    assert sorted(_saved(live)) == ["char:a", "char:b", "char:c"]


@_MONSTER_AIMING
def test_c26_s09_a_spent_recharge_action_sits_out_the_multiattack() -> None:
    doppelganger = _foe("mon:dop", cell(1, 0), "doppelganger", initiative=20, hp_current=52)
    handle, live = _start(
        [_sturdy("char:hero", cell(0, 0), 1)], [doppelganger], session="e2e-c26-s09"
    )
    _monster_turn(handle)
    _act(handle, "char:hero", intent_type="pass")
    turn_two = len(live.event_log)
    _monster_turn(handle)
    later = live.event_log[turn_two:]
    recharge = [e for e in later if isinstance(e, RechargeRolled)]
    assert [(e.action_slug, e.succeeded) for e in recharge] == [("unsettling-visage", False)]
    assert [e for e in later if isinstance(e, SaveRolled) and e.ability == "wis"] == []
    assert len([e for e in later if isinstance(e, AttackRolled)]) == 2


# ── the actor's side ─────────────────────────────────────────────────────────


@_ACTOR_SIDE
def test_c26_s05_sleep_spares_its_caster() -> None:
    def cast(session: str, **intent: Any):
        handle, live = _start(
            [_wizard(cell(5, 6), ["sleep"], {1: 1})],
            [
                _foe("mon:g1", cell(5, 5), initiative=10),
                _foe("mon:g2", cell(6, 5), initiative=5),
            ],
            session=session,
        )
        _act(
            handle,
            "char:wiz",
            intent_type="cast_spell",
            spell_id="sleep",
            target_id="mon:g1",
            slot_level=1,
            **intent,
        )
        return live

    live = cast("e2e-c26-s05")
    assert _saved(live) == ["mon:g1", "mon:g2"]
    [area] = _areas(live)
    assert (area.actor_id, area.source_id, area.shape, area.size_ft) == (
        "char:wiz",
        "sleep",
        "sphere",
        5,
    )
    assert (area.origin, area.direction) == (cell(5, 5), None)
    assert (area.affected_ids, area.excluded_ids) == (["mon:g1", "mon:g2"], ["char:wiz"])

    opted_in = cast("e2e-c26-s05-opt-in", excluded_target_ids=())
    assert _saved(opted_in)[:3] == ["char:wiz", "mon:g1", "mon:g2"]
    [area] = _areas(opted_in)
    assert (area.affected_ids, area.excluded_ids) == (["char:wiz", "mon:g1", "mon:g2"], [])


@_ACTOR_SIDE
def test_c26_s06_an_explicit_exclusion_replaces_the_default() -> None:
    handle, live = _start(
        [
            _wizard(cell(0, 0), ["weird"], {9: 1}),
            _pc("char:ally", cell(8, 9), initiative=15),
            _pc("char:ally2", cell(7, 8), initiative=14),
        ],
        [
            _foe("mon:foe", cell(8, 8), initiative=10),
            _foe("mon:foe2", cell(9, 8), initiative=5),
        ],
        session="e2e-c26-s06",
    )
    _act(
        handle,
        "char:wiz",
        intent_type="cast_spell",
        spell_id="weird",
        target_id="mon:foe",
        slot_level=9,
        excluded_target_ids=("char:ally",),
    )
    assert set(_saved(live)) == {"char:ally2", "mon:foe", "mon:foe2"}
    [area] = _areas(live)
    assert (area.affected_ids, area.excluded_ids) == (
        ["char:ally2", "mon:foe", "mon:foe2"],
        ["char:ally"],
    )


@_ACTOR_SIDE
def test_c26_s07_an_exclusion_on_an_area_with_no_choice_is_refused() -> None:
    handle, live = _start(
        [_wizard(cell(0, 5), ["fireball"], {3: 1}), _pc("char:ally", cell(8, 6), initiative=15)],
        [_foe("mon:foe", cell(8, 5))],
        session="e2e-c26-s07",
    )
    _act(
        handle,
        "char:wiz",
        intent_type="cast_spell",
        spell_id="fireball",
        target_id="mon:foe",
        slot_level=3,
        excluded_target_ids=("char:ally",),
    )
    assert [(e.spell_id, e.reason) for e in events_of(live, CastFailed)] == [
        ("fireball", "target_invalid")
    ]
    assert events_of(live, IntentSubmitted) == []
    assert events_of(live, SpellCast) == []
    assert live.spell_slots_by_entity["char:wiz"][3] == 1
    assert _combatant(live, "char:wiz").action_available is True
    assert live.initiative[live.current_turn_index].entity_id == "char:wiz"
    # The turn and the slot are still there: the same cast without the
    # exclusion resolves.
    _act(
        handle,
        "char:wiz",
        intent_type="cast_spell",
        spell_id="fireball",
        target_id="mon:foe",
        slot_level=3,
    )
    assert set(_saved(live)) == {"char:ally", "mon:foe"}
    assert live.spell_slots_by_entity["char:wiz"][3] == 0


@_ACTOR_SIDE
def test_c26_s08_phantasmal_force_affects_the_one_creature_named() -> None:
    handle, live = _start(
        [_wizard(cell(0, 5), ["phantasmal-force"], {2: 1})],
        [_foe("mon:foe", cell(7, 5), initiative=10), _foe("mon:bystander", cell(1, 5))],
        session="e2e-c26-s08",
    )
    _act(
        handle,
        "char:wiz",
        intent_type="cast_spell",
        spell_id="phantasmal-force",
        target_id="mon:foe",
        slot_level=2,
    )
    assert _saved(live) == ["mon:foe"]
    assert _areas(live) == []


# ── the corrected corpus ─────────────────────────────────────────────────────


def _monster_action(monster: str, action: str):
    found = BundledAssetLoader().get_monster(monster)
    assert found is not None
    return next(a for a in found.actions if a.slug == action)


def _area_target(monster: str, action: str):
    [activity] = [a for a in _monster_action(monster, action).activities if a.target.template.type]
    return activity.target


def test_c26_s10_every_dragon_breath_recharges_and_the_dragon_breathes_first() -> None:
    for monster, action in [
        ("adult-blue-dragon", "lightning-breath"),
        ("adult-copper-dragon", "acid-breath"),
        ("ancient-copper-dragon", "acid-breath"),
        ("ancient-gold-dragon", "fire-breath"),
        ("ancient-green-dragon", "poison-breath"),
        ("young-red-dragon", "fire-breath"),
        ("centaur-trooper", "trampling-charge"),
        ("tarrasque", "thunderous-bellow"),
    ]:
        assert _monster_action(monster, action).recharge == "5-6", (monster, action)

    dragon = _foe("mon:dragon", cell(5, 5), "young-red-dragon", initiative=20, hp_current=178)
    handle, live = _start([_sturdy("char:hero", cell(5, 6), 1)], [dragon], session="e2e-c26-s10")
    _monster_turn(handle)
    assert [(e.target_id, e.ability) for e in events_of(live, SaveRolled)] == [("char:hero", "dex")]
    _act(handle, "char:hero", intent_type="pass")
    _monster_turn(handle)
    assert [e.action_slug for e in events_of(live, RechargeRolled)] == ["fire-breath"]


def test_c26_s11_breath_shapes_and_sizes_follow_the_srd() -> None:
    for monster, action, shape, size in [
        ("adult-copper-dragon", "acid-breath", "line", "60"),
        ("adult-gold-dragon", "fire-breath", "cone", "60"),
        ("ancient-gold-dragon", "fire-breath", "cone", "90"),
        ("gold-dragon-wyrmling", "fire-breath", "cone", "15"),
        ("magma-mephit", "fire-breath", "cone", "15"),
        ("ancient-green-dragon", "poison-breath", "cone", "90"),
    ]:
        template = _area_target(monster, action).template
        assert (template.type, template.size) == (shape, size), (monster, action)


def test_c26_s12_each_creature_breaths_are_not_typed_enemy() -> None:
    for monster in [
        "adult-green-dragon",
        "ancient-green-dragon",
        "green-dragon-wyrmling",
        "young-green-dragon",
        "iron-golem",
    ]:
        assert _area_target(monster, "poison-breath").affects.type == "creature", monster
    # SRD 5.2 Planetar: "each enemy in a 20-foot-radius Sphere".
    assert _area_target("planetar", "holy-burst").affects.type == "enemy"


def test_c26_s13_of_your_choice_and_up_to_six_are_in_the_data() -> None:
    loader = BundledAssetLoader()

    def affects(entry, activity_id: str):
        return next(a for a in entry.activities if a.id == activity_id).target.affects

    sleep = affects(loader.get_spell("sleep"), "dnd5eactivity000")
    slow = affects(loader.get_spell("slow"), "dnd5eactivity000")
    mass_cure = affects(loader.get_spell("mass-cure-wounds"), "dnd5eactivity000")
    mace = affects(loader.get_item("mace-of-terror"), "owojSA2KZWmv61Nj")
    assert (sleep.choice, sleep.count) == (True, "")
    assert (slow.choice, slow.count) == (True, "6")
    assert (mass_cure.choice, mass_cure.count) == (True, "6")
    assert (mace.choice, mace.count) == (True, "")


# ── the actor's side, beyond spells ──────────────────────────────────────────


@_ACTOR_SIDE
def test_c26_s14_slow_affects_six_enemies_in_its_cube() -> None:
    goblins = [
        _foe(f"mon:g{i}", cell(col, row), initiative=10 - i)
        for i, (col, row) in enumerate(
            [(1, 0), (2, 0), (3, 0), (1, 1), (2, 1), (3, 1), (4, 0)], start=1
        )
    ]
    handle, live = _start(
        [_wizard(cell(0, 0), ["slow"], {3: 1}), _pc("char:ally", cell(1, 2), initiative=15)],
        goblins,
        session="e2e-c26-s14",
    )
    _act(
        handle,
        "char:wiz",
        intent_type="cast_spell",
        spell_id="slow",
        slot_level=3,
        direction=(1, 0),
    )
    assert _saved(live) == ["mon:g1", "mon:g2", "mon:g3", "mon:g4", "mon:g5", "mon:g6"]
    [area] = _areas(live)
    assert (area.shape, area.size_ft, area.origin, area.direction) == (
        "cube",
        40,
        cell(0, 0),
        (1, 0),
    )
    assert area.excluded_ids == ["char:ally", "mon:g7"]


@_ACTOR_SIDE
def test_c26_s15_a_breath_weapon_feature_is_an_area() -> None:
    drake = _pc(
        "char:drake", cell(0, 5), species_slug="dragonborn", character_level=5, constitution=14
    )
    handle, live = _start(
        [drake],
        [
            _foe("mon:a", cell(1, 5), initiative=10),
            _foe("mon:b", cell(2, 6)),
            _foe("mon:c", cell(6, 5)),
        ],
        session="e2e-c26-s15",
    )
    _act(
        handle,
        "char:drake",
        intent_type="use_feature",
        feature_id="breath-weapon",
        activity_id="dxCRYmNSSGp6L2yh",
        target_id="mon:a",
    )
    assert _saved(live) == ["mon:a", "mon:b"]
    [area] = _areas(live)
    assert (area.source_id, area.shape, area.size_ft, area.origin, area.direction) == (
        "breath-weapon",
        "cone",
        15,
        cell(0, 5),
        (1, 0),
    )


@_ACTOR_SIDE
def test_c26_s16_the_pipes_of_haunting_frighten_only_enemies_by_default() -> None:
    handle, live = _start(
        [_pc("char:bard", cell(5, 5)), _pc("char:ally", cell(6, 6), initiative=15)],
        [_foe("mon:foe", cell(5, 8))],
        session="e2e-c26-s16",
    )
    _act(
        handle,
        "char:bard",
        intent_type="use_item",
        item_id="pipes-of-haunting",
        target_id="mon:foe",
    )
    assert _saved(live) == ["mon:foe"]
    [area] = _areas(live)
    assert (area.source_id, area.shape, area.size_ft, area.origin, area.direction) == (
        "pipes-of-haunting",
        "emanation",
        30,
        cell(5, 5),
        None,
    )
    assert (area.affected_ids, area.excluded_ids) == (["mon:foe"], ["char:ally"])
