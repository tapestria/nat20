"""The four SRD 5.2 Fighting Style feats: the carrier, Defense and Archery;
Great Weapon Fighting and Two-Weapon Fighting."""

from __future__ import annotations

import random
from collections.abc import Iterator

import pytest
from dnd5e_srd_data.loader import BundledAssetLoader
from dnd5e_srd_data.schema.common import DamagePart
from pydantic import ValidationError

from dnd5e_engine import CharacterBuildSpec, CombatInstance, build_party_member, derive_sheet
from dnd5e_engine.activities.dice import roll_damage_part
from dnd5e_engine.events import AttackRolled, DamageApplied
from dnd5e_engine.lib_loader import set_lib_loader_for_tests
from dnd5e_engine.spatial import cell_id
from tests.c20_support import act, combatant, events, foe, pc, start

LOADER = BundledAssetLoader()


@pytest.fixture(autouse=True)
def _bundled_loader() -> Iterator[None]:
    set_lib_loader_for_tests(BundledAssetLoader())
    yield
    set_lib_loader_for_tests(None)


# ── Carrier, Defense, Archery ────────────────────────────────────────────────


def test_only_the_four_srd_styles_are_accepted() -> None:
    """Dueling and the other 2024 styles are not SRD 5.2 content."""
    with pytest.raises(ValidationError):
        pc(fighting_style="dueling")


def test_combat_styles_merge_feats_and_the_single_field() -> None:
    _, live = start(
        [pc(feats=("alert", "two-weapon-fighting", "archery"), fighting_style="defense")], seed=1
    )
    assert combatant(live).fighting_styles == ("archery", "defense", "two-weapon-fighting")


def test_a_champion_7_carries_both_styles_into_combat() -> None:
    """Additional Fighting Style (Champion 7): "You gain another Fighting Style
    feat of your choice." Both picks reach the live combatant."""
    member = build_party_member(
        CharacterBuildSpec(
            species_slug="human",
            class_slug="fighter",
            level=7,
            subclass_slug="champion",
            selected_choices=("archery", "two-weapon-fighting"),
        ),
        CombatInstance(entity_id="char:hero", name="Hero", zone_id=cell_id(0, 0)),
        loader=LOADER,
    )
    assert member.feats == ("archery", "two-weapon-fighting")
    _, live = start([member], seed=1)
    assert combatant(live).fighting_styles == ("archery", "two-weapon-fighting")


@pytest.mark.parametrize(
    ("equipment", "ac"),
    [
        (("chain-mail",), 17),
        (("leather-armor",), 12),
        (("chain-mail", "shield"), 19),
        ((), 10),
        (("shield",), 12),
    ],
)
def test_defense_adds_one_only_while_wearing_armor(equipment: tuple[str, ...], ac: int) -> None:
    """Defense: "While you're wearing Light, Medium, or Heavy armor, you gain a
    +1 bonus to Armor Class." A Fighter 1 with every score 10 (Chain Mail 16,
    Leather 11, a Shield +2); a Shield alone is not armor."""
    sheet = derive_sheet(
        CharacterBuildSpec(
            species_slug="human",
            class_slug="fighter",
            level=1,
            selected_choices=("defense",),
            equipment=equipment,
        ),
        loader=LOADER,
    )
    assert sheet.ac == ac


def test_defense_on_a_raw_spec_changes_nothing() -> None:
    """A hand-built spec's ``ac`` already reflects its armor; Defense is applied
    once, where ``derive_sheet`` knows the armor, never again in combat."""
    _, live = start([pc(ac=16, fighting_style="defense")], seed=1)
    assert combatant(live).ac == 16


@pytest.mark.parametrize(("weapon", "foe_cell"), [("longsword", (1, 0)), ("javelin", (6, 0))])
def test_archery_ignores_melee_weapons_even_thrown(weapon: str, foe_cell: tuple[int, int]) -> None:
    """Archery covers "attack rolls you make with Ranged weapons"; a thrown
    Javelin is a Melee weapon. Seed 7: d20 11 + 5 = 16 with or without it."""
    totals = []
    for style in (None, "archery"):
        handle, live = start(
            [pc(attack_bonus=5, fighting_style=style)],
            seed=7,
            encounter=[foe(ac=16, zone_id=cell_id(*foe_cell))],
        )
        act(handle, "char:hero", intent_type="attack", weapon_id=weapon, target_id="mon:foe")
        [attack] = events(live, AttackRolled)
        totals.append(attack.roll_total)
    assert totals == [16, 16]


# ── Great Weapon Fighting, Two-Weapon Fighting ───────────────────────────────


def _after_d20(seed: int) -> random.Random:
    rng = random.Random(seed)
    rng.randint(1, 20)
    return rng


def test_a_die_floor_raises_low_faces_without_changing_the_draws() -> None:
    """Seed 22 after its d20: d6 faces 2, 1, 5, 4 (a crit rolls all four)."""
    two_d6 = DamagePart(dice="2d6", damage_type="slashing")
    assert roll_damage_part(two_d6, _after_d20(22)) == 3
    assert roll_damage_part(two_d6, _after_d20(22), die_floor=3) == 6
    assert roll_damage_part(two_d6, _after_d20(22), crit=True) == 12
    assert roll_damage_part(two_d6, _after_d20(22), crit=True, die_floor=3) == 15


def _damage(style: str | None, *, two_handed: bool) -> list[int]:
    handle, live = start([pc(attack_bonus=5, fighting_style=style)], seed=10)
    act(
        handle,
        "char:hero",
        intent_type="attack",
        weapon_id="longsword",
        target_id="mon:foe",
        two_handed=two_handed,
    )
    return [e.amount for e in events(live, DamageApplied)]


@pytest.mark.parametrize(("two_handed", "with_style"), [(False, [1]), (True, [3])])
def test_gwf_on_a_versatile_weapon_needs_the_two_handed_grip(
    two_handed: bool, with_style: list[int]
) -> None:
    """Great Weapon Fighting: "...a Melee weapon that you are holding with two
    hands ... The weapon must have the Two-Handed or Versatile property". Seed
    10: d20 19 hits; the one-handed d8 and the two-handed d10 both show a 1
    (STR 10 adds nothing)."""
    assert _damage(None, two_handed=two_handed) == [1]
    assert _damage("great-weapon-fighting", two_handed=two_handed) == with_style


@pytest.mark.parametrize(
    ("equipment", "damage"), [(("greatsword",), [9]), (("greatsword", "shield"), [6])]
)
def test_gwf_needs_no_shield_in_the_other_hand(
    equipment: tuple[str, ...], damage: list[int]
) -> None:
    """Great Weapon Fighting: "...a Melee weapon that you are holding with two
    hands". A Shield takes one of them. S03's seed 22: d20 hits; the
    Greatsword's 2d6 shows 2 and 1, so 3 + 3 + STR 3 = 9 with the floor and
    2 + 1 + 3 = 6 without it."""
    handle, live = start(
        [
            pc(
                attack_bonus=8,
                strength=16,
                equipment=equipment,
                fighting_style="great-weapon-fighting",
            )
        ],
        seed=22,
    )
    act(handle, "char:hero", intent_type="attack", weapon_id="greatsword", target_id="mon:foe")
    assert [e.amount for e in events(live, DamageApplied)] == damage


def test_gwf_ignores_a_two_handed_ranged_weapon() -> None:
    """A Shortbow is Two-Handed but a Ranged weapon. At 20 ft, seed 2: d20 2
    hits AC 1; d6 1 + DEX 2 = 3 with or without the style."""
    for style in (None, "great-weapon-fighting"):
        handle, live = start(
            [pc(attack_bonus=5, dexterity=14, fighting_style=style)],
            seed=2,
            encounter=[foe(zone_id=cell_id(4, 0))],
        )
        act(handle, "char:hero", intent_type="attack", weapon_id="shortbow", target_id="mon:foe")
        assert [e.amount for e in events(live, DamageApplied)] == [3]


@pytest.mark.parametrize(("style", "offhand"), [(None, 2), ("two-weapon-fighting", 6)])
def test_twf_changes_only_the_offhand_swing(style: str | None, offhand: int) -> None:
    """S04's setup (seed 9): the Shortsword deals 9 either way; the Dagger's
    1d4 = 2 gains DEX +4 only with the style."""
    handle, live = start(
        [
            pc(
                attack_bonus=6,
                dexterity=18,
                equipment=("shortsword", "dagger"),
                fighting_style=style,
            )
        ],
        seed=9,
        encounter=[foe(zone_id=cell_id(0, 0))],
    )
    act(handle, "char:hero", intent_type="attack", weapon_id="shortsword", target_id="mon:foe")
    act(
        handle,
        "char:hero",
        intent_type="attack",
        weapon_id="dagger",
        target_id="mon:foe",
        use_bonus_action=True,
    )
    assert [e.amount for e in events(live, DamageApplied)] == [9, offhand]
