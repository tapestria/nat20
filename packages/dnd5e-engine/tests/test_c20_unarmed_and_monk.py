"""Unarmed Strike, Martial Arts and the Monk's bonus-funded strikes (SRD 5.2)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from dnd5e_srd_data.loader import BundledAssetLoader

from dnd5e_engine.events import AttackRolled, DamageApplied
from dnd5e_engine.lib_loader import set_lib_loader_for_tests
from dnd5e_engine.orchestrator import _unarmed_option_dc
from dnd5e_engine.types.combat import Combatant
from tests.c20_support import act, combatant, events, pc, start


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
