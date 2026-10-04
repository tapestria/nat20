"""SRD 5.2 area-targeting corrections (translator override tables).

The pinned Foundry sources disagree with the SRD 5.2 text on who an area
affects: four "of your choice" entries carry no ``affects.choice`` flag, two
"up to six creatures" spells carry no count, and fifteen monster actions carry
a wrong recharge, shape, size or target type. The translator corrects
them through ``tools.translators.foundry._AFFECTS_CORRECTIONS`` and
``_MONSTER_ACTION_CORRECTIONS``; these tests pin the corrected canonical output.
Each monster row quotes the SRD 5.2 stat-block sentence it follows.
"""

from __future__ import annotations

import pytest

from dnd5e_srd_data import BundledAssetLoader
from tools.translators.foundry import (
    _AFFECTS_CORRECTIONS,
    _MONSTER_ACTION_CORRECTIONS,
    _recharge_formula,
)

LOADER = BundledAssetLoader()


def _affects(entry, activity_id: str):
    [activity] = [a for a in entry.activities if a.id == activity_id]
    return activity.target.affects


def _action(monster: str, action: str):
    found = LOADER.get_monster(monster)
    assert found is not None
    [match] = [a for a in found.actions if a.slug == action]
    return match


def _area_target(monster: str, action: str):
    [activity] = [a for a in _action(monster, action).activities if a.target.template.type]
    return activity.target


@pytest.mark.parametrize(
    ("slug", "activity_id", "choice", "count", "grounding"),
    [
        ("sleep", "dnd5eactivity000", True, "", "Each creature of your choice"),
        ("slow", "dnd5eactivity000", True, "6", "up to six creatures of your choice"),
        ("mass-cure-wounds", "dnd5eactivity000", True, "6", "Choose up to six creatures"),
    ],
)
def test_spells_that_choose_their_creatures_say_so(
    slug: str, activity_id: str, choice: bool, count: str, grounding: str
) -> None:
    spell = LOADER.get_spell(slug)
    assert spell is not None
    assert grounding in spell.description
    affects = _affects(spell, activity_id)
    assert (affects.choice, affects.count) == (choice, count)


def test_the_mace_of_terrors_wave_chooses_its_creatures() -> None:
    mace = LOADER.get_item("mace-of-terror")
    assert mace is not None
    assert "Each creature of your choice within 30 feet of you" in mace.description
    affects = _affects(mace, "owojSA2KZWmv61Nj")
    assert (affects.choice, affects.count, affects.type) == (True, "", "creature")


def test_every_affects_correction_reached_the_corpus() -> None:
    entries = {
        "sleep": LOADER.get_spell("sleep"),
        "slow": LOADER.get_spell("slow"),
        "mass-cure-wounds": LOADER.get_spell("mass-cure-wounds"),
        "mace-of-terror": LOADER.get_item("mace-of-terror"),
    }
    assert {slug for slug, _ in _AFFECTS_CORRECTIONS} == set(entries)
    for (slug, activity_id), fields in _AFFECTS_CORRECTIONS.items():
        affects = _affects(entries[slug], activity_id)
        assert {name: getattr(affects, name) for name in fields} == fields


# "Lightning Breath (Recharge 5–6)", "Acid Breath (Recharge 5–6)", "Fire Breath
# (Recharge 5–6)", "Poison Breath (Recharge 5–6)", "Trampling Charge (Recharge
# 5–6)", "Thunderous Bellow (Recharge 5–6)".
@pytest.mark.parametrize(
    ("monster", "action"),
    [
        ("adult-blue-dragon", "lightning-breath"),
        ("adult-copper-dragon", "acid-breath"),
        ("ancient-copper-dragon", "acid-breath"),
        ("ancient-gold-dragon", "fire-breath"),
        ("ancient-green-dragon", "poison-breath"),
        ("young-red-dragon", "fire-breath"),
        ("centaur-trooper", "trampling-charge"),
        ("tarrasque", "thunderous-bellow"),
    ],
)
def test_these_actions_recharge_on_a_five_or_six(monster: str, action: str) -> None:
    assert _action(monster, action).recharge == "5-6"


# "each creature in an 60-foot-long, 5-foot-wide Line"; "each creature in a
# 60-foot Cone"; "... 90-foot Cone"; "... 15-foot Cone".
@pytest.mark.parametrize(
    ("monster", "action", "shape", "size", "width"),
    [
        ("adult-copper-dragon", "acid-breath", "line", "60", "5"),
        ("adult-gold-dragon", "fire-breath", "cone", "60", ""),
        ("ancient-gold-dragon", "fire-breath", "cone", "90", ""),
        ("gold-dragon-wyrmling", "fire-breath", "cone", "15", ""),
        ("magma-mephit", "fire-breath", "cone", "15", ""),
        ("ancient-green-dragon", "poison-breath", "cone", "90", ""),
    ],
)
def test_breath_templates_follow_the_srd(
    monster: str, action: str, shape: str, size: str, width: str
) -> None:
    template = _area_target(monster, action).template
    assert (template.type, template.size, template.width) == (shape, size, width)


# "Poison Breath ... each creature in a 60-foot Cone" (and the 90-, 15- and
# 30-foot cones of the other green dragons, the Iron Golem's 60-foot one).
@pytest.mark.parametrize(
    "monster",
    [
        "adult-green-dragon",
        "ancient-green-dragon",
        "green-dragon-wyrmling",
        "young-green-dragon",
        "iron-golem",
    ],
)
def test_each_creature_breaths_affect_every_creature(monster: str) -> None:
    assert _area_target(monster, "poison-breath").affects.type == "creature"


def test_an_each_enemy_area_keeps_its_type() -> None:
    # SRD 5.2 Planetar: "each enemy in a 20-foot-radius Sphere".
    assert _area_target("planetar", "holy-burst").affects.type == "enemy"


def test_every_monster_correction_reached_the_corpus() -> None:
    for (monster, action), fix in _MONSTER_ACTION_CORRECTIONS.items():
        if fix.recharge:
            assert _action(monster, action).recharge == fix.recharge, (monster, action)
        if fix.template_type or fix.template_size or fix.affects_type:
            target = _area_target(monster, action)
            got = (target.template.type, target.template.size, target.affects.type)
            want = (
                fix.template_type or got[0],
                fix.template_size or got[1],
                fix.affects_type or got[2],
            )
            assert got == want, (monster, action)


@pytest.mark.parametrize(
    ("recovery", "expected"),
    [
        ([{"period": "recharge", "type": "recoverAll"}], "6"),
        ([{"period": "recharge", "formula": "5", "type": "recoverAll"}], "5-6"),
        ([{"period": "recharge", "formula": "6", "type": "recoverAll"}], "6"),
        ([{"period": "recharge", "formula": "", "type": "recoverAll"}], None),
        ([{"period": "day", "type": "recoverAll"}], None),
        ([], None),
    ],
)
def test_a_recharge_with_no_formula_recharges_on_a_six(
    recovery: list[dict[str, str]], expected: str | None
) -> None:
    # Foundry ``UsesField.prepareData``: ``recovery.formula ??= "6"``.
    assert _recharge_formula({"recovery": recovery}) == expected
