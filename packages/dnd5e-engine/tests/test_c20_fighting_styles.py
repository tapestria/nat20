"""The four SRD 5.2 Fighting Style feats: carrier, Defense and Archery (Task 6);
Great Weapon Fighting and Two-Weapon Fighting (Task 7)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from dnd5e_srd_data.loader import BundledAssetLoader
from pydantic import ValidationError

from dnd5e_engine import CharacterBuildSpec, CombatInstance, build_party_member, derive_sheet
from dnd5e_engine.events import AttackRolled
from dnd5e_engine.lib_loader import set_lib_loader_for_tests
from dnd5e_engine.spatial import cell_id
from tests.c20_support import act, combatant, events, foe, pc, start

LOADER = BundledAssetLoader()


@pytest.fixture(autouse=True)
def _bundled_loader() -> Iterator[None]:
    set_lib_loader_for_tests(BundledAssetLoader())
    yield
    set_lib_loader_for_tests(None)


# ── Task 6 — carrier, Defense, Archery ───────────────────────────────────────


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
