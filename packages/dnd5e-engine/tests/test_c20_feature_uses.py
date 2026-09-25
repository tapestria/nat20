"""Limited-use caps and activity costs (Task 4) and Lay on Hands' pool (Task 5)."""

from __future__ import annotations

import random
from collections.abc import Iterator
from dataclasses import replace
from types import SimpleNamespace

import pytest
from dnd5e_srd_data.loader import BundledAssetLoader

from dnd5e_engine.activities.context import ActivityResolutionContext
from dnd5e_engine.activities.formula import resolve_roll_data
from dnd5e_engine.events import CastFailed, HealingApplied
from dnd5e_engine.lib_loader import set_lib_loader_for_tests
from dnd5e_engine.orchestrator import _feature_activity_cost, _feature_use_cap
from dnd5e_engine.rules.uses import UsesRollData
from dnd5e_engine.spatial import cell_id
from dnd5e_engine.types.combat import Combatant
from tests.c20_support import act, combatant, events, pc, start

LOADER = BundledAssetLoader()
FLURRY = "2ghJTBhilLrFn9xT"
PATIENT_DEFENSE_FOCUS = "7xj7b6e8tDznDSrE"
PATIENT_DEFENSE = "EFzidO6yAapw8d60"
HEAL = "gXZh9aGHcywV9huC"
REMOVE_POISON = "K6UeXQwTyDHWvis8"


@pytest.fixture(autouse=True)
def _bundled_loader() -> Iterator[None]:
    set_lib_loader_for_tests(BundledAssetLoader())
    yield
    set_lib_loader_for_tests(None)


def _counter(live, entity_id: str, feature: str) -> dict[str, int] | None:
    return live.custom_counters_by_entity.get(entity_id, {}).get(f"feature_use:{feature}")


# ── Task 4 — caps ────────────────────────────────────────────────────────────


def test_feature_use_cap_reads_prof_ability_and_class_level_maxes() -> None:
    roll_data = UsesRollData(
        proficiency_bonus=3, ability_modifiers={"cha": 3, "wis": -1}, class_levels={"paladin": 2}
    )

    def cap(expr: str) -> int | None:
        return _feature_use_cap(SimpleNamespace(uses=SimpleNamespace(max=expr)), roll_data)

    assert [
        cap("@prof"),
        cap("max(1, @abilities.cha.mod)"),
        cap("max(1,@abilities.wis.mod)"),
        cap("5 * @classes.paladin.levels"),
    ] == [3, 3, 1, 10]


@pytest.mark.parametrize(("spent", "refused"), [(1, False), (2, True)])
def test_a_prof_capped_trait_stops_at_the_proficiency_bonus(spent: int, refused: bool) -> None:
    """Adrenaline Rush: "You can use this trait a number of times equal to your
    Proficiency Bonus". PB 2 at level 1."""
    handle, live = start(
        [
            pc(
                class_slug="fighter",
                species_slug="orc",
                custom_counters={"feature_use:adrenaline-rush": {"spent": spent}},
            )
        ],
        seed=1,
    )
    act(handle, "char:hero", intent_type="use_feature", feature_id="adrenaline-rush")
    assert [e.reason for e in events(live, CastFailed)] == (
        ["no_uses_remaining"] if refused else []
    )
    assert _counter(live, "char:hero", "adrenaline-rush") == {"spent": 2}
    assert combatant(live).bonus_action_available is refused


@pytest.mark.parametrize(
    ("charisma", "spent", "refused"), [(16, 2, False), (16, 3, True), (8, 0, False), (8, 1, True)]
)
def test_bardic_inspiration_stops_at_the_charisma_modifier(
    charisma: int, spent: int, refused: bool
) -> None:
    """Bardic Inspiration: "a number of times equal to your Charisma modifier
    (minimum of once)". CHA 16 → 3; CHA 8 → 1."""
    handle, live = start(
        [
            pc(
                "char:bard",
                class_slug="bard",
                character_level=3,
                charisma=charisma,
                custom_counters={"feature_use:bardic-inspiration": {"spent": spent}},
            ),
            pc("char:ally", initiative=15, zone_id=cell_id(0, 1)),
        ],
        seed=1,
    )
    act(
        handle,
        "char:bard",
        intent_type="use_feature",
        feature_id="bardic-inspiration",
        target_id="char:ally",
    )
    assert [e.reason for e in events(live, CastFailed)] == (
        ["no_uses_remaining"] if refused else []
    )
    expected_spent = spent if refused else spent + 1
    assert _counter(live, "char:bard", "bardic-inspiration") == {"spent": expected_spent}


# ── Task 4 — activity costs ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("feature", "activity_id", "scaling_value", "cost"),
    [
        ("monks-focus", FLURRY, None, 1),
        ("monks-focus", PATIENT_DEFENSE_FOCUS, None, 1),
        ("monks-focus", PATIENT_DEFENSE, None, 0),
        ("lay-on-hands", HEAL, None, 1),
        ("lay-on-hands", HEAL, 7, 7),
        ("lay-on-hands", REMOVE_POISON, None, 5),
        ("indomitable", "84EBzlT1nDmNqhqM", None, 1),
        ("font-of-magic", "rYDgagyWjp6f3jtO", None, 1),
        ("relentless-rage", "Y2xWUsWmpklWLtVT", None, 0),
    ],
)
def test_activity_costs_follow_their_own_pool_consumption(
    feature: str, activity_id: str, scaling_value: int | None, cost: int
) -> None:
    doc = LOADER.get_feature(feature)
    assert doc is not None
    activity = next(a for a in doc.activities if a.id == activity_id)
    assert _feature_activity_cost(doc.activities, activity, scaling_value=scaling_value) == cost


def _monk_2(spent: int):
    counters = {"feature_use:monks-focus": {"spent": spent}}
    return start([pc(class_slug="monk", character_level=2, custom_counters=counters)], seed=1)


def test_free_patient_defense_spends_no_focus_point() -> None:
    """Patient Defense: "You can take the Disengage action as a Bonus Action.
    Alternatively, you can expend 1 Focus Point to take both the Disengage and
    the Dodge actions as a Bonus Action." Both points spent: the free option
    still works and spends nothing."""
    handle, live = _monk_2(spent=2)
    act(
        handle,
        "char:hero",
        intent_type="use_feature",
        feature_id="monks-focus",
        activity_id=PATIENT_DEFENSE,
    )
    assert not events(live, CastFailed)
    assert _counter(live, "char:hero", "monks-focus") == {"spent": 2}
    assert combatant(live).bonus_action_available is False


def test_paid_patient_defense_needs_a_focus_point() -> None:
    handle, live = _monk_2(spent=2)
    act(
        handle,
        "char:hero",
        intent_type="use_feature",
        feature_id="monks-focus",
        activity_id=PATIENT_DEFENSE_FOCUS,
    )
    assert [e.reason for e in events(live, CastFailed)] == ["no_uses_remaining"]
    assert combatant(live).bonus_action_available is True


@pytest.mark.parametrize(("spent", "refused"), [(5, False), (6, True)])
def test_remove_poison_costs_five_points_of_the_pool(spent: int, refused: bool) -> None:
    """Lay on Hands: "You can also expend 5 Hit Points from the pool of healing
    power to remove the Poisoned condition". Paladin 2: a pool of 10."""
    handle, live = start(
        [
            pc(
                "char:paladin",
                class_slug="paladin",
                character_level=2,
                custom_counters={"feature_use:lay-on-hands": {"spent": spent}},
            ),
            pc("char:ally", initiative=10, zone_id=cell_id(0, 1)),
        ],
        seed=1,
    )
    act(
        handle,
        "char:paladin",
        intent_type="use_feature",
        feature_id="lay-on-hands",
        activity_id=REMOVE_POISON,
        target_id="char:ally",
    )
    assert [e.reason for e in events(live, CastFailed)] == (
        ["no_uses_remaining"] if refused else []
    )
    assert _counter(live, "char:paladin", "lay-on-hands") == {"spent": spent if refused else 10}


def test_a_lone_activity_with_no_declared_cost_still_spends_a_use() -> None:
    """Indomitable (Fighter 9: one use per Long Rest): Foundry's only activity
    declares no consumption, but the SRD caps the feature."""
    handle, live = start([pc(class_slug="fighter", character_level=9)], seed=1)
    act(handle, "char:hero", intent_type="use_feature", feature_id="indomitable")
    assert _counter(live, "char:hero", "indomitable") == {"spent": 1}


# ── Task 5 — Lay on Hands' pool ──────────────────────────────────────────────


def _paladin(**fields):
    """A Paladin 2 (a pool of 10) at 0,0 and an ally at 0,1 with 1/200 HP."""
    paladin = {"class_slug": "paladin", "character_level": 2} | fields
    ally = pc("char:ally", initiative=10, hp_current=1, hp_max=200, zone_id=cell_id(0, 1))
    return start([pc("char:paladin", **paladin), ally], seed=1)


def _lay_on_hands(handle, activity_id: str = HEAL, **intent) -> None:
    act(
        handle,
        "char:paladin",
        intent_type="use_feature",
        feature_id="lay-on-hands",
        activity_id=activity_id,
        target_id="char:ally",
        **intent,
    )


def test_heal_draws_the_requested_points_and_spends_them() -> None:
    handle, live = _paladin()
    _lay_on_hands(handle, pool_points=7)
    assert [e.amount for e in events(live, HealingApplied)] == [7]
    assert _counter(live, "char:paladin", "lay-on-hands") == {"spent": 7}
    assert combatant(live, "char:paladin").bonus_action_available is False


def test_default_draw_is_one_point() -> None:
    """Without ``pool_points`` the Heal draws 1 point (Foundry's default draw)."""
    handle, live = _paladin()
    _lay_on_hands(handle)
    assert [e.amount for e in events(live, HealingApplied)] == [1]
    assert _counter(live, "char:paladin", "lay-on-hands") == {"spent": 1}


def test_an_overdraw_is_refused_before_the_bonus_action() -> None:
    """ "...up to the maximum amount remaining in the pool": 11 of 10 is refused."""
    handle, live = _paladin()
    _lay_on_hands(handle, pool_points=11)
    assert [e.reason for e in events(live, CastFailed)] == ["invalid_charge_spend"]
    assert not events(live, HealingApplied)
    assert _counter(live, "char:paladin", "lay-on-hands") is None
    assert combatant(live, "char:paladin").bonus_action_available is True


def test_pool_points_on_a_fixed_cost_activity_is_refused() -> None:
    handle, live = _paladin()
    _lay_on_hands(handle, REMOVE_POISON, pool_points=5)
    assert [e.reason for e in events(live, CastFailed)] == ["invalid_charge_spend"]
    assert _counter(live, "char:paladin", "lay-on-hands") is None


def test_an_empty_pool_refuses_the_default_draw() -> None:
    handle, live = _paladin(custom_counters={"feature_use:lay-on-hands": {"spent": 10}})
    _lay_on_hands(handle)
    assert [e.reason for e in events(live, CastFailed)] == ["no_uses_remaining"]


def test_the_pool_follows_the_paladin_level_in_a_multiclass() -> None:
    """Paladin 2 / Fighter 3: "five times your Paladin level" is 10, not 25."""
    handle, live = _paladin(classes={"paladin": 2, "fighter": 3}, character_level=5)
    _lay_on_hands(handle, pool_points=11)
    _lay_on_hands(handle, pool_points=10)
    assert [e.reason for e in events(live, CastFailed)] == ["invalid_charge_spend"]
    assert [e.amount for e in events(live, HealingApplied)] == [10]


def test_scaling_resolves_only_when_a_feature_supplies_it() -> None:
    """``@scaling`` is the drawn points; without them it still fails loudly."""
    caster = Combatant(
        entity_id="char:paladin", entity_type="Character", name="P", initiative=1, hp_current=1
    )
    ctx = ActivityResolutionContext(
        rng=random.Random(1),
        caster=caster,
        targets=[],
        event_emitter=lambda _event: None,
        caster_abilities={},
        scaling_value=4,
    )
    assert resolve_roll_data("@scaling", ctx) == "4"
    with pytest.raises(ValueError, match="@scaling"):
        resolve_roll_data("@scaling", replace(ctx, scaling_value=None))
