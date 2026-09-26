"""The transformation core (C21): stash, swap and revert a creature's stat
block for SRD 5.2 Wild Shape and Polymorph, driven directly through
``_apply_transform`` / ``_end_transform`` (Tasks 9 and 10 add the producers)."""

from __future__ import annotations

import random
from collections.abc import Iterator
from typing import Any

import pytest
from dnd5e_srd_data.loader import BundledAssetLoader

from dnd5e_engine import get_live
from dnd5e_engine.activities.build_context import build_activity_context
from dnd5e_engine.activities.conjuration import (
    TRANSFORM_FORM_FLAG,
    StatBlockMagnitudes,
    TransformSource,
)
from dnd5e_engine.activities.monster_actions import multiattack_count
from dnd5e_engine.events import (
    AttackFailed,
    CastFailed,
    ConcentrationDropped,
    EffectApplied,
    EffectExpired,
    TempHpApplied,
)
from dnd5e_engine.lib_loader import set_lib_loader_for_tests
from dnd5e_engine.orchestrator import (
    _apply_transform,
    _emit,
    _end_transform,
    _LiveCombat,
    _stat_block_magnitudes_of,
)
from dnd5e_engine.specs import PartyMemberSpec
from dnd5e_engine.types.effects import ActiveEffect
from dnd5e_engine.views import TransformView
from tests.c21_support import act, combatant, druid, events, foe, pc, start, wizard

LOADER = BundledAssetLoader()
DRUID = "char:druid"


@pytest.fixture(autouse=True)
def _bundled_loader() -> Iterator[None]:
    set_lib_loader_for_tests(BundledAssetLoader())
    yield
    set_lib_loader_for_tests(None)


def _shape(
    live: _LiveCombat,
    entity_id: str,
    form_slug: str,
    *,
    source: TransformSource = "wild-shape",
    temp_hp: int = 6,
    caster_id: str = "char:wiz",
) -> None:
    """Transform ``entity_id`` as the Wild Shape / Polymorph producers will:
    Wild Shape's own effect on the druid, or Polymorph's concentration effect
    keyed to its caster."""
    form = LOADER.get_monster(form_slug)
    assert form is not None
    if source == "wild-shape":
        effect = ActiveEffect(
            id="effect:wild-shape",
            name="Wild Shape",
            origin=f"cast:wild-shape:{entity_id}",
            target_id=entity_id,
            flags={TRANSFORM_FORM_FLAG: form_slug},
        )
    else:
        effect = ActiveEffect(
            id="effect:polymorph",
            name="Polymorph",
            origin=f"cast:polymorph:{caster_id}",
            target_id=entity_id,
            flags={"concentration": True, TRANSFORM_FORM_FLAG: form_slug},
        )
    _apply_transform(live, entity_id, form, source=source, effect=effect, temp_hp=temp_hp)


def _minded_druid(**fields: Any) -> PartyMemberSpec:
    """A Druid 6 with a distinct mind and its own proficiencies."""
    base: dict[str, Any] = {
        "intelligence": 12,
        "wisdom": 16,
        "charisma": 8,
        "save_proficiencies": ("int", "wis"),
        "skill_proficiencies": ("nature", "perception"),
        "skill_expertise": ("nature",),
    }
    return druid(**(base | fields))


@pytest.mark.parametrize(
    ("slug", "count"),
    [("ape", 2), ("black-bear", 2), ("brown-bear", 2), ("wolf", 1), ("giant-badger", 1)],
)
def test_multiattack_count(slug: str, count: int) -> None:
    """Ape and Black Bear: "makes two … attacks"; Brown Bear: "one Bite attack
    and one Claw attack"; no Multiattack: 1."""
    monster = LOADER.get_monster(slug)
    assert monster is not None
    assert multiattack_count(monster) == count


def test_wild_shape_swaps_the_body_and_keeps_the_mind() -> None:
    """SRD 5.2 Wild Shape into a Giant Badger (AC 13, STR 13, DEX 10, CON 17,
    Burrow 10 ft, Darkvision 60 ft, Perception): the druid keeps INT / WIS /
    CHA, its Proficiency Bonus and expertise, and adds the badger's
    proficiencies to its own. 6 Temporary Hit Points (Druid level)."""
    _, live = start([_minded_druid()], seed=1)
    _shape(live, DRUID, "giant-badger")
    shaped = combatant(live, DRUID)
    assert (shaped.ac, shaped.strength, shaped.dexterity, shaped.constitution) == (13, 13, 10, 17)
    assert (shaped.intelligence, shaped.wisdom, shaped.charisma) == (12, 16, 8)
    assert shaped.proficiency_bonus_override is None
    assert shaped.save_proficiencies == ["int", "wis"]
    assert shaped.skill_proficiencies == ["nature", "perception"]
    assert shaped.skill_expertise == ["nature"]
    assert (shaped.base_speed, shaped.movement_modes.burrow) == (30, 10)
    assert shaped.senses.darkvision == 60
    assert (shaped.melee_reach_ft, shaped.trait_mechanics, shaped.temp_hp) == (5, [], 6)
    assert live.tracked_temp_hp[DRUID] == 6
    transform = live.transforms[DRUID]
    assert (transform.form_slug, transform.source, transform.effect_id, transform.origin) == (
        "giant-badger",
        "wild-shape",
        "effect:wild-shape",
        "cast:wild-shape:char:druid",
    )
    assert (transform.form_proficiency_bonus, transform.attacks_per_action) == (2, 1)
    assert (transform.clears_temp_hp_on_end, transform.original_monster_slug) == (False, None)
    assert DRUID not in live.monster_slug_by_entity
    [applied] = events(live, EffectApplied)
    assert applied.effect.flags == {TRANSFORM_FORM_FLAG: "giant-badger"}
    assert [(e.target_id, e.amount) for e in events(live, TempHpApplied)] == [(DRUID, 6)]


def test_polymorph_replaces_the_whole_stat_block() -> None:
    """SRD 5.2 Polymorph: "The target's game statistics are replaced by the
    stat block of the chosen Beast". A Tough becomes a Black Bear (AC 11; STR
    15, DEX 12, CON 14, INT 2, WIS 12, CHA 7; PB 2; Perception; no Pack
    Tactics) and acts from the bear's actions; 19 Temporary Hit Points."""
    _, live = start([wizard()], seed=1, encounter=[foe(monster_template_slug="tough")])
    _shape(live, "mon:foe", "black-bear", source="polymorph", temp_hp=19)
    bear = combatant(live, "mon:foe")
    assert bear.ac == 11
    assert (bear.strength, bear.dexterity, bear.constitution) == (15, 12, 14)
    assert (bear.intelligence, bear.wisdom, bear.charisma) == (2, 12, 7)
    assert (bear.proficiency_bonus_override, bear.save_proficiencies) == (2, [])
    assert (bear.skill_proficiencies, bear.skill_expertise) == (["perception"], [])
    assert (bear.trait_mechanics, bear.spellcasting_ability, bear.temp_hp) == ([], None, 19)
    assert (bear.movement_modes.climb, bear.movement_modes.swim) == (30, 30)
    assert live.monster_slug_by_entity["mon:foe"] == "black-bear"
    assert live.monster_action_uses_by_entity["mon:foe"] == {}
    transform = live.transforms["mon:foe"]
    assert (transform.original_monster_slug, transform.attacks_per_action) == ("tough", 2)
    assert transform.clears_temp_hp_on_end is True


def test_revert_restores_every_stashed_field() -> None:
    """Ending the transformation through its effect restores the creature
    exactly: stats, stat block and actions; Polymorph's own Temporary Hit
    Points vanish."""
    _, live = start([wizard()], seed=1, encounter=[foe(monster_template_slug="tough")])
    before = combatant(live, "mon:foe")
    uses_before = live.monster_action_uses_by_entity.get("mon:foe")
    _shape(live, "mon:foe", "black-bear", source="polymorph", temp_hp=19)
    _end_transform(live, "mon:foe", "remove_ieffect")
    [expired] = events(live, EffectExpired)
    assert (expired.effect_id, expired.origin, expired.reason) == (
        "effect:polymorph",
        "cast:polymorph:char:wiz",
        "remove_ieffect",
    )
    assert combatant(live, "mon:foe") == before
    assert live.monster_slug_by_entity["mon:foe"] == "tough"
    assert live.monster_action_uses_by_entity.get("mon:foe") is uses_before
    assert live.transforms == {}
    assert live.tracked_temp_hp["mon:foe"] == 0


def test_wild_shape_reverts_and_keeps_its_temp_hp() -> None:
    _, live = start([_minded_druid()], seed=1)
    before = combatant(live, DRUID)
    _shape(live, DRUID, "giant-badger")
    _end_transform(live, DRUID, "remove_ieffect")
    assert combatant(live, DRUID) == before.model_copy(update={"temp_hp": 6})
    assert live.tracked_temp_hp[DRUID] == 6


def test_a_second_transform_ends_the_first() -> None:
    """Wild Shape used again: the badger form ends (``remove_ieffect``) before
    the Wolf's lands, so the stash keeps the druid's own statistics."""
    _, live = start([druid()], seed=1)
    _shape(live, DRUID, "giant-badger")
    _shape(live, DRUID, "wolf")
    assert [(e.effect_id, e.reason) for e in events(live, EffectExpired)] == [
        ("effect:wild-shape", "remove_ieffect")
    ]
    transform = live.transforms[DRUID]
    assert (transform.form_slug, transform.stash["ac"], combatant(live, DRUID).ac) == (
        "wolf",
        10,
        12,
    )
    assert [e.id for e in live.active_effects[DRUID]] == ["effect:wild-shape"]


def test_ending_a_concentration_transform_drops_its_casters_concentration() -> None:
    """Polymorph lives on its caster's concentration: ending it is a
    concentration drop, which cascades into the revert."""
    _, live = start([wizard()], seed=1, encounter=[foe(monster_template_slug="tough")])
    _shape(live, "mon:foe", "black-bear", source="polymorph", temp_hp=19)
    live.concentration_chain["char:wiz"] = [
        ("mon:foe", "effect:polymorph", "cast:polymorph:char:wiz")
    ]
    _end_transform(live, "mon:foe", "concentration_drop")
    assert [(e.target_id, e.effect_name) for e in events(live, ConcentrationDropped)] == [
        ("char:wiz", "effect:polymorph")
    ]
    assert [e.reason for e in events(live, EffectExpired)] == ["concentration_drop"]
    assert "char:wiz" not in live.concentration_chain
    assert live.monster_slug_by_entity["mon:foe"] == "tough"


@pytest.mark.parametrize(
    ("source", "before", "granted", "after_end"),
    [
        ("polymorph", 0, 19, 0),
        ("polymorph", 25, 25, 25),
        ("wild-shape", 0, 6, 6),
    ],
)
def test_only_polymorphs_own_temp_hp_vanish(
    source: TransformSource, before: int, granted: int, after_end: int
) -> None:
    """Temporary Hit Points don't stack: a Polymorph grant that did not raise
    the bucket is not the spell's to take away. Wild Shape's stay."""
    _, live = start([druid()], seed=1)
    if before:
        _emit(live, TempHpApplied(target_id=DRUID, amount=before))
    _shape(live, DRUID, "black-bear", source=source, temp_hp=19 if source == "polymorph" else 6)
    assert live.tracked_temp_hp[DRUID] == granted
    _end_transform(live, DRUID, "remove_ieffect")
    assert (live.tracked_temp_hp[DRUID], combatant(live, DRUID).temp_hp) == (after_end, after_end)


def test_movement_clamps_to_the_forms_speed() -> None:
    """A Crab walks 20 ft: the druid's unspent 30 ft drops to 20 and stays 20
    after the revert (a transformation never adds movement)."""
    _, live = start([druid()], seed=1)
    _shape(live, DRUID, "crab")
    crab = combatant(live, DRUID)
    assert (crab.base_speed, crab.movement_remaining) == (20, 20)
    _end_transform(live, DRUID, "remove_ieffect")
    reverted = combatant(live, DRUID)
    assert (reverted.base_speed, reverted.movement_remaining) == (30, 20)


@pytest.mark.parametrize(
    ("member", "form", "source", "attacks"),
    [
        ({"class_slug": "druid", "character_level": 6}, "ape", "wild-shape", 2),
        ({"class_slug": "fighter", "character_level": 5}, "wolf", "wild-shape", 2),
        ({"class_slug": "fighter", "character_level": 5}, "wolf", "polymorph", 1),
    ],
)
def test_the_attack_count_comes_from_the_form(
    member: dict[str, Any], form: str, source: TransformSource, attacks: int
) -> None:
    """The form's Multiattack sets the count; Wild Shape keeps the creature's
    own Extra Attack ("you retain … class features"), Polymorph does not."""
    _, live = start([pc(**member)], seed=1)
    _shape(live, "char:hero", form, source=source)
    assert live.transforms["char:hero"].attacks_per_action == attacks


def test_the_context_uses_the_stat_block_magnitudes() -> None:
    """With the carrier the entity-type model is bypassed: the scores and PB
    are the stat block's, and no fixed to-hit or save DC overrides them. A
    template-less foe with ``attack_bonus`` 4 otherwise gets the uniform
    10 + 2 × 4 = 18 scores, PB 2, to-hit 4 and DC 8 + 4 = 12."""
    _, live = start([pc()], seed=1, encounter=[foe(attack_bonus=4)])
    monster = combatant(live, "mon:foe")
    magnitudes = StatBlockMagnitudes(
        ability_scores={"str": 15, "dex": 12, "con": 14, "int": 2, "wis": 12, "cha": 7},
        proficiency_bonus=2,
    )
    common: dict[str, Any] = {
        "rng": random.Random(1),
        "event_emitter": lambda _event: None,
        "slot_level": None,
        "base_spell_level": None,
        "spellcasting_ability": None,
        "concentration": False,
        "source_passive_effects": [],
        "spell_book": {},
        "passive_damage_modifiers": {},
        "save_modifiers": {},
    }
    plain = build_activity_context(monster, [], **common)
    assert (plain.caster_abilities["str"], plain.caster_proficiency_bonus) == (18, 2)
    assert (plain.attack_bonus_override, plain.save_dc_override) == (4, 12)
    carried = build_activity_context(monster, [], stat_block_magnitudes=magnitudes, **common)
    assert carried.caster_abilities == dict(magnitudes.ability_scores)
    assert carried.caster_proficiency_bonus == 2
    assert (carried.attack_bonus_override, carried.save_dc_override) == (None, None)
    assert carried.stat_block_magnitudes == magnitudes


def test_stat_block_magnitudes_of_a_transformed_actor() -> None:
    """The badger's body, the druid's mind, the form's PB."""
    _, live = start([_minded_druid()], seed=1)
    assert _stat_block_magnitudes_of(live, combatant(live, DRUID)) is None
    _shape(live, DRUID, "giant-badger")
    assert _stat_block_magnitudes_of(live, combatant(live, DRUID)) == StatBlockMagnitudes(
        ability_scores={"str": 13, "dex": 10, "con": 17, "int": 12, "wis": 16, "cha": 8},
        proficiency_bonus=2,
    )


_CAST = {"intent_type": "cast_spell", "spell_id": "thunderwave", "target_id": "mon:foe"}
_READY = {"intent_type": "ready", "spell_id": "thunderwave", "reaction_trigger": "hit_by_attack"}
_SWING = {"intent_type": "attack", "weapon_id": "quarterstaff", "target_id": "mon:foe"}


@pytest.mark.parametrize(
    ("intent", "failure"), [(_CAST, CastFailed), (_READY, CastFailed), (_SWING, AttackFailed)]
)
def test_a_shape_shifted_creature_cannot_cast_or_wield(
    intent: dict[str, Any], failure: type[CastFailed] | type[AttackFailed]
) -> None:
    """SRD 5.2 Wild Shape: "You can't cast spells"; objects follow "the form's
    limbs". Refused before anything is spent; the turn stays open."""
    handle, live = start([druid(spells_known=["thunderwave"], spell_slots={1: 1})], seed=1)
    _shape(live, DRUID, "giant-badger")
    act(handle, DRUID, **intent)
    [refused] = events(live, failure)
    assert refused.reason == ("no_spellcasting" if failure is CastFailed else "action_unavailable")
    shaped = combatant(live, DRUID)
    assert (shaped.action_available, shaped.bonus_action_available) == (True, True)
    assert live.spell_slots_by_entity[DRUID] == {1: 1}
    assert live.current_actor_id == DRUID


def test_a_running_concentration_survives_the_swap() -> None:
    """SRD 5.2 Wild Shape: "shapeshifting doesn't break your Concentration"."""
    blessed = ActiveEffect(
        id="effect:blessed",
        name="Blessed",
        origin="cast:blessed:char:druid",
        target_id=DRUID,
        flags={"concentration": True},
    )
    _, live = start([druid()], seed=1, active_effects=[blessed])
    _shape(live, DRUID, "giant-badger")
    assert live.concentration_chain[DRUID] == [(DRUID, "effect:blessed", "cast:blessed:char:druid")]
    assert combatant(live, DRUID).concentration_effect_id == "effect:blessed"


def test_the_host_view_names_the_form() -> None:
    handle, live = start([druid()], seed=1)
    _shape(live, DRUID, "giant-badger")
    assert get_live(handle).transformations == {
        DRUID: TransformView(
            entity_id=DRUID,
            form_slug="giant-badger",
            source="wild-shape",
            effect_id="effect:wild-shape",
            origin="cast:wild-shape:char:druid",
        )
    }
    _end_transform(live, DRUID, "remove_ieffect")
    assert get_live(handle).transformations == {}
