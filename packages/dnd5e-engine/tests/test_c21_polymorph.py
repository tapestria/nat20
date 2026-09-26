"""Polymorph (C21). SRD 5.2: "The target must succeed on a Wisdom saving throw or
shape-shift into a Beast form for the duration. That form can be any Beast you
choose that has a Challenge Rating equal to or less than the target's (or the
target's level if it doesn't have a Challenge Rating). ... The target gains a
number of Temporary Hit Points equal to the Hit Points of the Beast form. These
Temporary Hit Points vanish if any remain when the spell ends. The spell ends
early on the target if it has no Temporary Hit Points left."

The Wizard 9 (INT 18) casts at DC 16. Each seeded test's first d20 is the
target's Wisdom save (WIS 10, +0, no proficiency): seed 1 rolls 5 (fails), seed
2 rolls 2 (fails), seed 6 rolls 19 (succeeds).
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any

import pytest
from dnd5e_srd_data.loader import BundledAssetLoader
from dnd5e_srd_data.schema.monster import Monster

from dnd5e_engine import CombatHandle, end_combat, get_live
from dnd5e_engine.activities.conjuration import (
    CONJURATION_ALLOWLIST,
    TRANSFORM_RIDERS,
    TransformRider,
)
from dnd5e_engine.events import (
    AttackRolled,
    CastFailed,
    DamageApplied,
    EffectApplied,
    EffectExpired,
    SaveRolled,
    SpellCast,
)
from dnd5e_engine.lib_loader import get_lib_loader, set_lib_loader_for_tests
from dnd5e_engine.orchestrator import _emit, _LiveCombat
from dnd5e_engine.spatial import cell_id
from dnd5e_engine.specs import EncounterMemberSpec
from tests.c21_support import act, combatant, events, foe, monster_turn, pc, start, wizard

WIZ = "char:wiz"
FOE = "mon:foe"
POLYMORPH = "effect:polymorph"
SLOTS = {2: 2, 4: 1}


@pytest.fixture(autouse=True)
def _bundled_loader() -> Iterator[None]:
    set_lib_loader_for_tests(BundledAssetLoader())
    yield
    set_lib_loader_for_tests(None)


def _form(slug: str) -> Monster:
    form = get_lib_loader().get_monster(slug)
    assert form is not None, slug
    return form


def _tough(**fields: Any) -> EncounterMemberSpec:
    """A Tough (CR 1/2; WIS 10, no save proficiency) with 40 HP and AC 10."""
    base: dict[str, Any] = {
        "monster_template_slug": "tough",
        "hp_current": 40,
        "hp_max": 40,
        "ac": 10,
    }
    return foe(**(base | fields))


def _polymorph(
    handle: CombatHandle, target_id: str = FOE, form_id: str | None = "giant-badger"
) -> None:
    act(
        handle,
        WIZ,
        intent_type="cast_spell",
        spell_id="polymorph",
        target_id=target_id,
        form_id=form_id,
        slot_level=4,
    )


def _polymorph_ends(live: _LiveCombat) -> list[str]:
    return [e.reason for e in events(live, EffectExpired) if e.effect_id == POLYMORPH]


def test_polymorph_is_an_allowlisted_failed_save_rider() -> None:
    assert CONJURATION_ALLOWLIST["polymorph"] == "transform_rider"
    assert dict(TRANSFORM_RIDERS) == {
        "polymorph": TransformRider(trigger="failed_save", source="polymorph")
    }


def test_a_failed_save_turns_the_target_into_the_beast() -> None:
    """Seed 1: the Tough's Wisdom save rolls 5 against DC 16. It becomes a Giant
    Badger (AC 13, 15 HP): exactly 15 Temporary Hit Points, its own 40 Hit
    Points untouched, its actions the Badger's. The form's effect is the
    wizard's concentration, with no anchor beside it."""
    handle, live = start([wizard()], seed=1, encounter=[_tough()])
    _polymorph(handle)
    (save,) = events(live, SaveRolled)
    target = combatant(live, FOE)
    assert (save.target_id, save.ability, save.succeeded) == (FOE, "wis", False)
    assert (live.tracked_temp_hp[FOE], live.tracked_hp[FOE], target.ac) == (15, 40, 13)
    assert live.monster_slug_by_entity[FOE] == "giant-badger"
    assert get_live(handle).transformations[FOE].source == "polymorph"
    assert live.concentration_chain[WIZ] == [(FOE, POLYMORPH, f"cast:polymorph:{WIZ}")]
    assert not any(e.effect.flags.get("concentration_anchor") for e in events(live, EffectApplied))
    assert live.spell_slots_by_entity[WIZ] == {2: 2, 4: 0}


def test_a_successful_save_applies_nothing_but_the_wizard_concentrates() -> None:
    """Seed 6: the save rolls 19. No form, no Temporary Hit Points; the cast
    still concentrates (the anchor), as every concentration spell now does."""
    handle, live = start([wizard()], seed=6, encounter=[_tough()])
    _polymorph(handle)
    assert FOE not in get_live(handle).transformations
    assert (live.tracked_temp_hp.get(FOE, 0), combatant(live, FOE).ac) == (0, 10)
    assert live.concentration_chain[WIZ] == [(WIZ, POLYMORPH, f"cast:polymorph:{WIZ}")]


@pytest.mark.parametrize(
    ("target", "form_id", "legal"),
    [
        (_tough(), "giant-badger", True),
        (_tough(), "black-bear", True),
        (_tough(), "brown-bear", False),
        (_tough(), "giant-insect", False),
        (_tough(), "tough", False),
        (_tough(), "no-such-beast", False),
        (_tough(), None, False),
        (foe(hp_current=40, hp_max=40, ac=10), "giant-badger", False),
    ],
    ids=[
        "cr-quarter-under-half",
        "cr-half-equal",
        "cr-1-over-half",
        "summon-stat-block",
        "a-humanoid",
        "unknown-slug",
        "no-form",
        "template-less-target",
    ],
)
def test_the_form_gate_on_a_monster(
    target: EncounterMemberSpec, form_id: str | None, legal: bool
) -> None:
    """ "...any Beast you choose that has a Challenge Rating equal to or less
    than the target's": the Tough is CR 1/2. A target with neither a Challenge
    Rating nor a level (a template-less foe) is refused rather than guessed. A
    refusal spends nothing and rolls no save."""
    handle, live = start([wizard()], seed=1, encounter=[target])
    _polymorph(handle, form_id=form_id)
    if legal:
        assert (events(live, CastFailed), live.spell_slots_by_entity[WIZ]) == ([], {2: 2, 4: 0})
    else:
        assert [(e.spell_id, e.reason) for e in events(live, CastFailed)] == [
            ("polymorph", "invalid_form")
        ]
        assert (live.spell_slots_by_entity[WIZ], events(live, SaveRolled)) == (SLOTS, [])
        assert (combatant(live, WIZ).action_available, live.current_actor_id) == (True, WIZ)


@pytest.mark.parametrize(
    ("form_id", "legal"), [("brown-bear", True), ("giant-boar", False)], ids=["cr-1", "cr-2"]
)
def test_a_character_target_is_measured_by_its_level(form_id: str, legal: bool) -> None:
    """ "...(or the target's level if it doesn't have a Challenge Rating)": a
    level-1 ally takes a CR 1 form, not a CR 2 one."""
    ally = pc("char:ally", initiative=15, zone_id=cell_id(0, 1))
    handle, live = start([wizard(), ally], seed=1)
    _polymorph(handle, target_id="char:ally", form_id=form_id)
    assert [e.reason for e in events(live, CastFailed)] == ([] if legal else ["invalid_form"])


def _beasts() -> list[str]:
    loader = BundledAssetLoader()
    return [
        slug
        for slug in loader.list_slugs("monsters")
        if (monster := loader.get_monster(slug)) is not None and monster.creature_type == "beast"
    ]


@pytest.mark.parametrize("target", ["tough", "level-9"])
@pytest.mark.parametrize("slug", _beasts())
def test_every_corpus_beast_polymorphs_or_is_refused_before_spending(
    slug: str, target: str
) -> None:
    """Every corpus Beast against a CR 1/2 Tough and a level-9 ally. Seed 2: the
    target's save rolls 2, so a legal form always lands, with the form's Hit
    Points as Temporary Hit Points and its AC; anything else is refused before
    the slot is spent. Giant Insect (a summon stat block) is never a form."""
    form = _form(slug)
    ally = pc("char:ally", initiative=15, character_level=9, zone_id=cell_id(0, 1))
    party, target_id, ceiling = (
        ([wizard()], FOE, 0.5) if target == "tough" else ([wizard(), ally], "char:ally", 9.0)
    )
    handle, live = start(party, seed=2, encounter=[_tough()])
    _polymorph(handle, target_id=target_id, form_id=slug)
    legal = form.cr <= ceiling and "@flags.dnd5e.summon" not in form.model_dump_json()
    shaped = get_live(handle).transformations.get(target_id)
    if legal:
        assert shaped is not None
        assert shaped.form_slug == slug
        assert (live.tracked_temp_hp[target_id], combatant(live, target_id).ac) == (
            form.hp,
            form.ac,
        )
    else:
        assert shaped is None
        assert [e.reason for e in events(live, CastFailed)] == ["invalid_form"]
        assert live.spell_slots_by_entity[WIZ] == SLOTS


def test_excess_damage_after_polymorph_ends_hits_own_hp() -> None:
    """20 damage: the form's 15 Temporary Hit Points absorb 15 and the spell
    ends ("no Temporary Hit Points left"); the other 5 land on the Tough's own
    Hit Points, and its own statistics are back."""
    handle, live = start([wizard()], seed=1, encounter=[_tough()])
    _polymorph(handle)
    _emit(
        live, DamageApplied(target_id=FOE, amount=20, damage_type="bludgeoning", is_overkill=False)
    )
    assert _polymorph_ends(live) == ["temp_hp_depleted"]
    assert (live.tracked_hp[FOE], live.tracked_temp_hp[FOE], combatant(live, FOE).ac) == (35, 0, 10)
    assert live.monster_slug_by_entity[FOE] == "tough"
    assert FOE not in get_live(handle).transformations
    assert WIZ not in live.concentration_chain


def test_damage_the_temp_hp_absorb_keeps_the_form() -> None:
    """10 damage leaves 5 of the 15 Temporary Hit Points: the form stays."""
    handle, live = start([wizard()], seed=1, encounter=[_tough()])
    _polymorph(handle)
    _emit(
        live, DamageApplied(target_id=FOE, amount=10, damage_type="bludgeoning", is_overkill=False)
    )
    assert (_polymorph_ends(live), live.tracked_temp_hp[FOE], live.tracked_hp[FOE]) == ([], 5, 40)


@pytest.mark.parametrize("how", ["drop-intent", "failed-concentration-save"])
def test_losing_concentration_reverts_the_form_and_clears_its_temp_hp(how: str) -> None:
    """ "These Temporary Hit Points vanish if any remain when the spell ends."
    The drop intent comes on the wizard's next turn (the Tough, 45 feet away,
    closes in without reaching it). The failed save: seed 2 rolls the Tough's
    Wisdom save 2, then the wizard's DC 10 Constitution save 3."""
    if how == "drop-intent":
        handle, live = start([wizard()], seed=1, encounter=[_tough(zone_id=cell_id(9, 9))])
        _polymorph(handle)
        monster_turn(handle)
        act(handle, WIZ, intent_type="drop_concentration")
    else:
        handle, live = start([wizard()], seed=2, encounter=[_tough()])
        _polymorph(handle)
        _emit(live, DamageApplied(target_id=WIZ, amount=10, damage_type="fire", is_overkill=False))
    assert _polymorph_ends(live) == ["concentration_drop"]
    assert (live.tracked_temp_hp[FOE], combatant(live, FOE).ac) == (0, 10)
    assert FOE not in get_live(handle).transformations


def test_polymorphed_monster_attacks_with_its_form() -> None:
    """The Tough's own turn picks from the Giant Badger's stat block, at its real
    numbers ("Bite. Melee Attack Roll: +3, reach 5 ft. 6 (2d4 + 1) Piercing
    damage"). Seed 1: the save rolls 5; the Bite rolls d20 19 → 22 against the
    wizard's AC 10 and 2d4 1 + 3, plus 1 → 5."""
    handle, live = start([wizard()], seed=1, encounter=[_tough()])
    _polymorph(handle)
    monster_turn(handle)
    (roll,) = events(live, AttackRolled)
    bite = next(e for e in events(live, DamageApplied) if e.target_id == WIZ)
    assert (roll.attacker_id, roll.modifier, roll.roll_total, roll.is_hit) == (FOE, 3, 22, True)
    assert (bite.amount, bite.damage_type) == (5, "piercing")


@pytest.mark.parametrize(
    ("form_id", "template", "ability", "dc"),
    [
        # "Web ... Dexterity Saving Throw: DC 13": 8 + DEX 3 + PB 2.
        ("giant-spider", "ogre", "dex", 13),
        # "Boulder Toss ... Dexterity Saving Throw: DC 17": 8 + STR 6 + PB 3.
        ("giant-ape", "stone-giant", "dex", 17),
        # "Constrict. Strength Saving Throw: DC 14": 8 + STR 4 + PB 2.
        ("giant-constrictor-snake", "ogre", "str", 14),
        # "Cacophony ... Wisdom Saving Throw: DC 10": the stat block's own 8 + PB 2.
        ("swarm-of-ravens", "ogre", "wis", 10),
    ],
)
def test_a_polymorphed_monster_uses_its_forms_save_action(
    form_id: str, template: str, ability: str, dc: int
) -> None:
    """A form's save action carries its DC as a stat-block calculation, not the
    template's fixed DC. Seed 1: the target fails its Wisdom save, and its own
    turn picks the form's save action against the wizard at the SRD-printed DC
    (the snake Bites first, and the wizard's Constitution save for Polymorph's
    concentration is not that action's); the turn then passes on."""
    handle, live = start(
        [wizard(hp_current=300, hp_max=300)],
        seed=1,
        encounter=[foe(monster_template_slug=template, hp_current=200, hp_max=200)],
    )
    _polymorph(handle, form_id=form_id)
    assert live.monster_slug_by_entity[FOE] == form_id
    monster_turn(handle)
    saves = [(e.ability, e.dc) for e in events(live, SaveRolled) if e.target_id == WIZ]
    assert [save for save in saves if save[0] == ability] == [(ability, dc)]
    assert live.initiative[live.current_turn_index].entity_id == WIZ


def test_a_polymorph_running_at_combat_end_leaves_no_temp_hp_in_the_outcome() -> None:
    """Effects end with the combat, and Polymorph's Temporary Hit Points "vanish
    if any remain when the spell ends": the outcome carries the creature's own
    state. Seed 3: the fighter's Wisdom save (WIS 3) fails; the Giant
    Crocodile's 85 Hit Points are its Temporary Hit Points until the end."""
    fighter = pc("char:f", initiative=19, class_slug="fighter", character_level=9, wisdom=3)
    handle, live = start(
        [wizard(zone_id=cell_id(0, 1)), fighter], seed=3, encounter=[foe(zone_id=cell_id(5, 5))]
    )
    _polymorph(handle, target_id="char:f", form_id="giant-crocodile")
    assert live.tracked_temp_hp["char:f"] == 85
    outcome = asyncio.run(end_combat(handle)).outcome
    assert outcome.residual_temp_hp == {}
    assert outcome.residual_hp == {WIZ: 40, "char:f": 40}


def test_a_polymorphed_character_cannot_release_its_readied_spell() -> None:
    """ "...it can't speak or cast spells." The engine casts a readied spell as
    it releases it, so a readied Shield lets the trigger pass while its reactor
    is a Beast: no Reaction, slot or effect is spent, and the Shield stays
    armed (shapeshifting "doesn't break your Concentration"). Seed 1: the ally
    wizard's Polymorph save (WIS 6) fails; the foe's swing then lands on the
    Giant Badger's AC 13."""
    reader = wizard(
        "char:a", wisdom=6, spells_known=["shield"], spell_slots={1: 2}, zone_id=cell_id(0, 0)
    )
    caster = wizard(initiative=19, zone_id=cell_id(0, 1))
    handle, live = start(
        [reader, caster], seed=1, encounter=[foe(attack_bonus=5, damage_dice="1d6")]
    )
    act(handle, "char:a", intent_type="ready", spell_id="shield", reaction_trigger="hit_by_attack")
    _polymorph(handle, target_id="char:a")
    assert "char:a" in live.transforms
    monster_turn(handle)
    assert [e.target_id for e in events(live, AttackRolled)] == ["char:a"]
    assert [e.spell_id for e in events(live, SpellCast)] == ["polymorph"]
    assert live.spell_slots_by_entity["char:a"] == {1: 2}
    assert combatant(live, "char:a").reaction_available
    assert [p.spell_id for p in live.pending_reactions] == ["shield"]


def test_a_polymorphed_character_cannot_cast() -> None:
    """ "...it can't speak or cast spells." Seed 1: the ally wizard's save rolls
    5; on its turn its Hold Person is refused and its slot is kept."""
    ally = wizard("char:ally", initiative=15)
    handle, live = start([wizard(), ally], seed=1, encounter=[_tough()])
    _polymorph(handle, target_id="char:ally")
    act(
        handle,
        "char:ally",
        intent_type="cast_spell",
        spell_id="hold-person",
        target_id=FOE,
        slot_level=2,
    )
    assert [e.reason for e in events(live, CastFailed)] == ["no_spellcasting"]
    assert live.spell_slots_by_entity["char:ally"] == SLOTS
