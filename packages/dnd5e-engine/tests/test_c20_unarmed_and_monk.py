"""Unarmed Strike, Martial Arts and the Monk's bonus-funded strikes (SRD 5.2)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from dnd5e_srd_data.loader import BundledAssetLoader

from dnd5e_engine import PlayerIntent
from dnd5e_engine.events import AttackFailed, AttackRolled, DamageApplied
from dnd5e_engine.lib_loader import set_lib_loader_for_tests
from dnd5e_engine.orchestrator import _classify_attack_funding, _unarmed_option_dc
from dnd5e_engine.spatial import cell_id
from dnd5e_engine.types.combat import Combatant
from tests.c20_support import act, combatant, events, foe, monster_turn, pc, start


@pytest.fixture(autouse=True)
def _bundled_loader() -> Iterator[None]:
    set_lib_loader_for_tests(BundledAssetLoader())
    yield
    set_lib_loader_for_tests(None)


def _unarmed(handle, actor: str = "char:hero", **intent) -> None:
    act(
        handle,
        actor,
        intent_type="attack",
        weapon_id="unarmed-strike",
        target_id="mon:foe",
        **intent,
    )


# ── Task 2 — Unarmed Strike base damage ──────────────────────────────────────


def test_unarmed_strike_deals_one_plus_strength() -> None:
    """SRD 5.2 Unarmed Strike: "On a hit, the target takes Bludgeoning damage
    equal to 1 plus your Strength modifier." Seed 2: d20 2 + STR 3 + PB 2 = 7
    hits AC 1; the damage is 1 + 3 = 4 and no damage die is drawn."""
    handle, live = start([pc(strength=16)], seed=2)
    _unarmed(handle)
    [hit] = events(live, DamageApplied)
    assert (hit.amount, hit.damage_type, hit.source_id) == (4, "bludgeoning", "unarmed-strike")


def test_a_critical_unarmed_strike_has_no_die_to_double() -> None:
    """Seed 5: a natural 20. "1 plus your Strength modifier" carries no die,
    so the Critical Hit deals the same 4."""
    handle, live = start([pc(strength=16)], seed=5)
    _unarmed(handle)
    [attack] = events(live, AttackRolled)
    assert attack.is_crit
    assert [e.amount for e in events(live, DamageApplied)] == [4]


# ── Task 8 — Martial Arts ────────────────────────────────────────────────────


def _first_damage(live) -> int:
    return events(live, DamageApplied)[0].amount


def test_martial_arts_uses_dex_for_the_unarmed_attack_roll() -> None:
    """Dexterous Attacks: "You can use your Dexterity modifier instead of your
    Strength modifier for the attack and damage rolls of your Unarmed Strikes
    and Monk weapons." Monk 1, STR 8, DEX 16, engine-computed to-hit: 3 + PB 2."""
    handle, live = start([pc(class_slug="monk", strength=8, dexterity=16)], seed=4)
    _unarmed(handle)
    [attack] = events(live, AttackRolled)
    assert attack.modifier == 5


def test_the_martial_arts_die_grows_with_monk_level() -> None:
    """Monk 5: the die is a d8. Seed 4: d20 8 hits; d8 5 + DEX 3 = 8."""
    handle, live = start(
        [pc(class_slug="monk", character_level=5, dexterity=16, attack_bonus=5)], seed=4
    )
    _unarmed(handle)
    assert _first_damage(live) == 8


@pytest.mark.parametrize(
    ("equipment", "damage"), [((), 6), (("leather-armor",), 2), (("shield",), 2)]
)
def test_armor_or_a_shield_turns_martial_arts_off(equipment: tuple[str, ...], damage: int) -> None:
    """ "...and you aren't wearing armor or wielding a Shield." Monk 1, STR 12,
    DEX 16, seed 4: with Martial Arts d6 3 + DEX 3 = 6; without it the Unarmed
    Strike deals 1 + STR 1 = 2 and no die is drawn."""
    handle, live = start(
        [pc(class_slug="monk", strength=12, dexterity=16, attack_bonus=5, equipment=equipment)],
        seed=4,
    )
    _unarmed(handle)
    assert _first_damage(live) == damage


@pytest.mark.parametrize(("class_slug", "damage"), [("monk", 6), ("fighter", 2)])
def test_a_monk_weapon_keeps_its_own_die_and_swaps_in_dex(class_slug: str, damage: int) -> None:
    """Quarterstaff d6 against Monk 1's d6: the weapon's die stays (the Martial
    Arts die is no bigger), and Martial Arts swaps STR -1 for DEX +3. Seed 4:
    d20 8 hits; d6 3."""
    handle, live = start(
        [pc(class_slug=class_slug, strength=8, dexterity=16, attack_bonus=5)], seed=4
    )
    act(handle, "char:hero", intent_type="attack", weapon_id="quarterstaff", target_id="mon:foe")
    assert _first_damage(live) == damage


def test_a_non_monk_weapon_gets_no_martial_arts() -> None:
    """A Longsword is a Martial weapon without Light: STR -1. Seed 4: d8 5 → 4."""
    handle, live = start([pc(class_slug="monk", strength=8, dexterity=16, attack_bonus=5)], seed=4)
    act(handle, "char:hero", intent_type="attack", weapon_id="longsword", target_id="mon:foe")
    assert _first_damage(live) == 4


def test_martial_arts_lets_grapple_and_shove_use_dex() -> None:
    """ "...when you use the Grapple or Shove option of your Unarmed Strike, you
    can use your Dexterity modifier instead of your Strength modifier to
    determine the save DC." 8 + DEX 3 + PB 2 = 13; STR 10 gives 10."""
    monk = Combatant(
        entity_id="char:monk",
        entity_type="Character",
        name="Monk",
        initiative=20,
        hp_current=10,
        class_slug="monk",
        dexterity=16,
    )
    fighter = monk.model_copy(update={"class_slug": "fighter"})
    armored = monk.model_copy(update={"worn_armor": "light"})
    assert [_unarmed_option_dc(c) for c in (monk, fighter, armored)] == [13, 10, 10]


def test_worn_armor_comes_from_equipment() -> None:
    _, live = start([pc(equipment=("chain-mail", "shield", "longsword"))], seed=1)
    hero = combatant(live)
    assert (hero.worn_armor, hero.shield_equipped) == ("heavy", True)


# ── Task 9 — Flurry of Blows, Bonus Unarmed Strike ───────────────────────────

_FLURRY = "2ghJTBhilLrFn9xT"


def _monk(level: int = 2, *, seed: int = 4, **start_kwargs: Any):
    """A Monk with DEX 16 and a pinned +5 to hit against the AC 1 foe. Seed 4
    draws d20 8, d6 3, d20 4, d6 6, d20 13, d6 4: at Monk 1-4 every Unarmed
    Strike hits for its Martial Arts d6 + DEX 3."""
    return start(
        [pc(class_slug="monk", character_level=level, dexterity=16, attack_bonus=5)],
        seed=seed,
        **start_kwargs,
    )


def _flurry(handle) -> None:
    act(
        handle,
        "char:hero",
        intent_type="use_feature",
        feature_id="monks-focus",
        activity_id=_FLURRY,
    )


def test_flurry_of_blows_makes_two_unarmed_strikes_as_its_bonus_action() -> None:
    """SRD 5.2 Monk's Focus: "Flurry of Blows. You can expend 1 Focus Point to
    make two Unarmed Strikes as a Bonus Action." Monk 2, seed 4: the strikes
    hit for 3 + 3 = 6 and 6 + 3 = 9, spend no Action and keep the turn; the
    next Unarmed Strike is the Attack action (4 + 3 = 7) and ends the turn."""
    handle, live = _monk()
    _flurry(handle)
    assert combatant(live).flurry_strikes_remaining == 2
    _unarmed(handle)
    _unarmed(handle)
    monk = combatant(live)
    assert (monk.flurry_strikes_remaining, monk.action_available, monk.bonus_action_available) == (
        0,
        True,
        False,
    )
    assert live.current_actor_id == "char:hero"
    _unarmed(handle)
    assert [e.amount for e in events(live, DamageApplied)] == [6, 9, 7]
    assert live.current_actor_id == "mon:foe"
    assert live.custom_counters_by_entity["char:hero"]["feature_use:monks-focus"]["spent"] == 1


def test_heightened_focus_makes_it_three_strikes() -> None:
    """Heightened Focus (Monk 10): "You can expend 1 Focus Point to use Flurry of
    Blows and make three Unarmed Strikes with it instead of two." None of them
    touches the Attack action's two swings."""
    handle, live = _monk(10)
    _flurry(handle)
    for _ in range(3):
        _unarmed(handle)
    monk = combatant(live)
    assert len(events(live, AttackRolled)) == 3
    assert (monk.flurry_strikes_remaining, monk.action_available, monk.attacks_remaining) == (
        0,
        True,
        2,
    )


def test_owed_flurry_strikes_keep_the_turn_after_the_attack_action() -> None:
    """A one-attack Monk who takes the Attack action (a Mace) while Flurry
    strikes are owed keeps the turn for them; ``pass`` ends it."""
    handle, live = _monk()
    _flurry(handle)
    act(handle, "char:hero", intent_type="attack", weapon_id="mace", target_id="mon:foe")
    assert live.current_actor_id == "char:hero"
    _unarmed(handle)
    _unarmed(handle)
    assert len(events(live, AttackRolled)) == 3
    act(handle, "char:hero", intent_type="pass")
    assert live.current_actor_id == "mon:foe"


def test_unused_flurry_strikes_lapse_at_the_next_turn() -> None:
    handle, live = _monk()
    _flurry(handle)
    _unarmed(handle)
    act(handle, "char:hero", intent_type="pass")
    assert combatant(live).flurry_strikes_remaining == 1
    monster_turn(handle)
    assert live.current_actor_id == "char:hero"
    assert combatant(live).flurry_strikes_remaining == 0


def test_a_flurry_strike_out_of_reach_consumes_nothing() -> None:
    """The foe is 10 ft away: the reach gate refuses the strike before it is paid."""
    handle, live = _monk(encounter=[foe(zone_id=cell_id(2, 0))])
    _flurry(handle)
    _unarmed(handle)
    assert [e.reason for e in events(live, AttackFailed)] == ["out_of_range"]
    assert combatant(live).flurry_strikes_remaining == 2


def test_the_bonus_unarmed_strike_spends_the_bonus_action() -> None:
    """SRD 5.2 Martial Arts: "Bonus Unarmed Strike. You can make an Unarmed
    Strike as a Bonus Action." Monk 1, seed 4: it hits for 6 and keeps the
    turn and the Action; a second one finds no Bonus Action (turn kept,
    nothing drawn); the Attack action's strike hits for 6 + 3 = 9 and ends the
    turn."""
    handle, live = _monk(1)
    _unarmed(handle, use_bonus_action=True)
    monk = combatant(live)
    assert (monk.action_available, monk.bonus_action_available) == (True, False)
    _unarmed(handle, use_bonus_action=True)
    assert [e.reason for e in events(live, AttackFailed)] == ["no_action_economy"]
    assert live.current_actor_id == "char:hero"
    _unarmed(handle)
    assert [e.amount for e in events(live, DamageApplied)] == [6, 9]
    assert live.current_actor_id == "mon:foe"


@pytest.mark.parametrize(
    ("class_slug", "equipment"), [("fighter", ()), ("monk", ("leather-armor",))]
)
def test_without_martial_arts_use_bonus_action_changes_nothing(
    class_slug: str, equipment: tuple[str, ...]
) -> None:
    """No Martial Arts (a Fighter, or a Monk in armor): ``use_bonus_action`` on
    an Unarmed Strike is an ordinary Attack-action swing, as today. Seed 2:
    d20 2 + STR 3 + PB 2 hits; 1 + 3 = 4; the one-attack turn ends."""
    handle, live = start([pc(class_slug=class_slug, strength=16, equipment=equipment)], seed=2)
    _unarmed(handle, use_bonus_action=True)
    assert [e.amount for e in events(live, DamageApplied)] == [4]
    assert live.current_actor_id == "mon:foe"
    assert combatant(live).bonus_action_available


@pytest.mark.parametrize(
    ("weapon_id", "state", "use_bonus_action", "funding"),
    [
        ("unarmed-strike", {}, False, "action"),
        ("unarmed-strike", {}, True, "martial_arts_bonus"),
        ("unarmed-strike", {"worn_armor": "light"}, True, "action"),
        ("unarmed-strike", {"flurry_strikes_remaining": 1}, False, "flurry"),
        ("unarmed-strike", {"flurry_strikes_remaining": 1}, True, "flurry"),
        ("quarterstaff", {"flurry_strikes_remaining": 1}, False, "action"),
        (
            "dagger",
            {
                "attack_action_engaged": True,
                "attacks_remaining": 0,
                "light_weapon_swing_slug": "shortsword",
            },
            True,
            "light_offhand",
        ),
    ],
)
def test_attack_funding_priority(
    weapon_id: str, state: dict[str, Any], use_bonus_action: bool, funding: str
) -> None:
    """One classifier, in priority order: the Light extra attack, then an owed
    Flurry strike, then the Bonus Unarmed Strike, else the Attack action."""
    monk = Combatant(
        entity_id="char:monk",
        entity_type="Character",
        name="Monk",
        initiative=20,
        hp_current=10,
        class_slug="monk",
        character_level=2,
    ).model_copy(update=state)
    intent = PlayerIntent(
        intent_type="attack",
        weapon_id=weapon_id,
        target_id="mon:foe",
        use_bonus_action=use_bonus_action,
    )
    weapon = BundledAssetLoader().get_weapon(weapon_id)
    assert _classify_attack_funding(monk, intent, weapon) == funding
