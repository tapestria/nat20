"""Wild Shape (C21). SRD 5.2: "As a Bonus Action, you shape-shift into a Beast
form that you have learned for this feature ... You stay in that form for a
number of hours equal to half your Druid level or until you use Wild Shape
again, have the Incapacitated condition, or die. You can also leave the form
early as a Bonus Action." "When you assume a Wild Shape form, you gain a number
of Temporary Hit Points equal to your Druid level." ``PlayerIntent.form_id``
names the form, checked against the Beast Shapes table before anything is
spent; known forms are the host's to track.

Wild Shape draws nothing, so each seeded number below comes from the one roll
the test names.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest
from dnd5e_srd_data.loader import BundledAssetLoader
from dnd5e_srd_data.schema.common import TransformActivity
from dnd5e_srd_data.schema.monster import Monster

from dnd5e_engine import CombatHandle, end_combat, get_live
from dnd5e_engine.activities.conjuration import (
    TRANSFORM_FORM_FLAG,
    WILD_SHAPE_TIERS,
    WildShapeTier,
    wild_shape_tier,
)
from dnd5e_engine.events import (
    CastFailed,
    ConditionApplied,
    DamageApplied,
    EffectApplied,
    EffectExpired,
)
from dnd5e_engine.lib_loader import get_lib_loader, set_lib_loader_for_tests
from dnd5e_engine.orchestrator import _apply_transform, _emit, _LiveCombat
from dnd5e_engine.spatial import cell_id
from dnd5e_engine.specs import EncounterMemberSpec
from dnd5e_engine.types.effects import ActiveEffect
from tests.c21_support import act, combatant, druid, events, foe, monster_turn, start, wizard

DRUID = "char:druid"
WILD_SHAPE = "effect:wild-shape"
_ROWS = {2: (0.25, False), 4: (0.5, False), 8: (1.0, True)}


@pytest.fixture(autouse=True)
def _bundled_loader() -> Iterator[None]:
    set_lib_loader_for_tests(BundledAssetLoader())
    yield
    set_lib_loader_for_tests(None)


def _form(slug: str) -> Monster:
    form = get_lib_loader().get_monster(slug)
    assert form is not None, slug
    return form


def _beasts() -> list[str]:
    loader = BundledAssetLoader()
    return [
        slug
        for slug in loader.list_slugs("monsters")
        if (monster := loader.get_monster(slug)) is not None and monster.creature_type == "beast"
    ]


_BEASTS = _beasts()


def _legal(form: Monster, level: int) -> bool:
    """The Beast Shapes row for Druid ``level``: Max CR 1/4, 1/2 or 1 and a Fly
    Speed only from level 8 — never a summon stat block (Giant Insect)."""
    max_cr, fly_ok = _ROWS[level]
    return (
        form.ac is not None
        and form.cr <= max_cr
        and (not form.movement.fly or fly_ok)
        and "@flags.dnd5e.summon" not in form.model_dump_json()
    )


def _wild_shape(handle: CombatHandle, form_id: str | None = None) -> None:
    act(handle, DRUID, intent_type="use_feature", feature_id="wild-shape", form_id=form_id)


def _uses_spent(live: _LiveCombat) -> int:
    counter = live.custom_counters_by_entity.get(DRUID, {}).get("feature_use:wild-shape", {})
    return counter.get("spent", 0)


def _wild_shape_ends(live: _LiveCombat) -> list[str]:
    return [e.reason for e in events(live, EffectExpired) if e.effect_id == WILD_SHAPE]


def _far_foe() -> EncounterMemberSpec:
    """A foe 45 feet away: its turn closes in without reaching the druid."""
    return foe(zone_id=cell_id(9, 9))


def _next_turn(handle: CombatHandle) -> None:
    act(handle, DRUID, intent_type="pass")
    monster_turn(handle)


def test_wild_shape_survives_losing_its_temp_hp() -> None:
    """The breaker's hit spends the 6 Temporary Hit Points and 27 of the
    druid's own Hit Points; the form stays, because it ends on reuse,
    Incapacitated, death or the Bonus-Action leave — not when its Temporary
    Hit Points run out. Seed 13: after the druid passes, the breaker rolls
    d20 9 + 10 = 19 against the Giant Badger's AC 13 and deals 8d6 = 33."""
    breaker = foe(
        entity_id="mon:breaker",
        name="Breaker",
        initiative=10,
        hp_current=50,
        hp_max=50,
        ac=10,
        attack_bonus=10,
        damage_dice="8d6",
        zone_id=cell_id(0, 1),
    )
    handle, live = start([druid()], seed=13, encounter=[breaker])
    _wild_shape(handle, "giant-badger")
    assert (combatant(live, DRUID).ac, live.tracked_temp_hp[DRUID]) == (13, 6)
    act(handle, DRUID, intent_type="pass")
    monster_turn(handle)
    (hit,) = [e for e in events(live, DamageApplied) if e.target_id == DRUID]
    assert hit.amount == 33
    assert (live.tracked_hp[DRUID], live.tracked_temp_hp[DRUID]) == (13, 0)
    assert combatant(live, DRUID).ac == 13
    assert get_live(handle).transformations[DRUID].form_slug == "giant-badger"
    assert _wild_shape_ends(live) == []


def test_wild_shapes_temp_hp_carry_into_the_outcome() -> None:
    """Only Polymorph's Temporary Hit Points vanish with the combat; Wild
    Shape's are ordinary ones, kept like any others: the Druid 6's 6."""
    handle, live = start([druid()], seed=1)
    _wild_shape(handle, "giant-badger")
    assert DRUID in live.transforms
    outcome = asyncio.run(end_combat(handle)).outcome
    assert outcome.residual_temp_hp == {DRUID: 6}


def test_wild_shape_is_a_bonus_action_that_keeps_the_turn() -> None:
    """A Druid 6 (three uses) spends one use and its Bonus Action and keeps its
    Action. The form rides a non-concentration effect naming the Beast."""
    handle, live = start([druid()], seed=1)
    _wild_shape(handle, "giant-badger")
    (applied,) = [e.effect for e in events(live, EffectApplied) if e.effect.id == WILD_SHAPE]
    shaped = combatant(live, DRUID)
    assert (applied.origin, applied.flags) == (
        f"cast:wild-shape:{DRUID}",
        {TRANSFORM_FORM_FLAG: "giant-badger"},
    )
    assert (shaped.bonus_action_available, shaped.action_available) == (False, True)
    assert (live.current_actor_id, _uses_spent(live), DRUID in live.concentration_chain) == (
        DRUID,
        1,
        False,
    )


def test_the_beast_shapes_table_matches_the_features_corpus_profiles() -> None:
    """SRD 5.2 Beast Shapes: Max CR 1/4 at Druid 2, 1/2 at 4 and 1 at 8, with a
    Fly Speed only from 8. The feature's transform profiles say the same (a
    profile's ``movement`` lists the speed it excludes; Wild Shape is a
    level-2 feature, so the first profile has no minimum level)."""
    feature = get_lib_loader().get_feature("wild-shape")
    assert feature is not None
    (activity,) = feature.activities
    assert isinstance(activity, TransformActivity)
    from_corpus = tuple(
        WildShapeTier(
            min_level=profile.level.min or 2,
            max_cr=float(profile.cr),
            fly_allowed="fly" not in profile.movement,
        )
        for profile in activity.profiles
    )
    assert from_corpus == WILD_SHAPE_TIERS
    low, mid, high = WILD_SHAPE_TIERS
    assert [wild_shape_tier(level) for level in (1, 2, 3, 4, 7, 8, 20)] == [
        None,
        low,
        low,
        mid,
        mid,
        high,
        high,
    ]


def test_the_beast_shapes_rows_admit_41_48_and_70_corpus_beasts() -> None:
    """The corpus has 92 Beasts; Giant Insect is never a form. The sweep below
    is only as good as ``_legal``, so this pins what it admits."""
    counts = {level: sum(_legal(_form(slug), level) for slug in _BEASTS) for level in _ROWS}
    assert (len(_BEASTS), counts) == (92, {2: 41, 4: 48, 8: 70})


@pytest.mark.parametrize("level", sorted(_ROWS))
@pytest.mark.parametrize("slug", _BEASTS)
def test_every_corpus_beast_transforms_or_is_refused_before_spending(slug: str, level: int) -> None:
    """Every corpus Beast at every row of the table: a legal form is taken (the
    Bonus Action and one use spent, the form's AC on the initiative entry);
    anything else is refused with ``invalid_form`` before either is spent."""
    form = _form(slug)
    handle, live = start([druid(character_level=level)], seed=1)
    _wild_shape(handle, slug)
    shaped = get_live(handle).transformations.get(DRUID)
    now = combatant(live, DRUID)
    if _legal(form, level):
        assert shaped is not None
        assert shaped.form_slug == slug
        assert (now.ac, _uses_spent(live), now.bonus_action_available) == (form.ac, 1, False)
    else:
        assert shaped is None
        assert [e.reason for e in events(live, CastFailed)] == ["invalid_form"]
        assert (now.ac, _uses_spent(live), now.bonus_action_available) == (10, 0, True)


@pytest.mark.parametrize(
    ("level", "form_id", "legal"),
    [
        (2, "wolf", True),
        (2, "black-bear", False),
        (2, "giant-bat", False),
        (4, "black-bear", True),
        (4, "brown-bear", False),
        (4, "giant-bat", False),
        (8, "giant-bat", True),
        (8, "brown-bear", True),
        (8, "giant-insect", False),
        (8, "tough", False),
        (8, "no-such-beast", False),
    ],
    ids=[
        "cr-quarter-at-2",
        "cr-half-at-2",
        "flyer-at-2",
        "cr-half-at-4",
        "cr-1-at-4",
        "flyer-at-4",
        "flyer-at-8",
        "cr-1-at-8",
        "summon-stat-block",
        "a-humanoid",
        "unknown-slug",
    ],
)
def test_the_form_gate_by_name(level: int, form_id: str, legal: bool) -> None:
    """The named edges: CR above the row, a Fly Speed before level 8, Giant
    Insect (a summon stat block), a non-Beast and a slug the corpus lacks."""
    handle, live = start([druid(character_level=level)], seed=1)
    _wild_shape(handle, form_id)
    assert (DRUID in get_live(handle).transformations) is legal
    assert [e.reason for e in events(live, CastFailed)] == ([] if legal else ["invalid_form"])


def test_no_form_outside_a_form_is_refused_before_spending() -> None:
    """Without ``form_id`` there is no Beast to become (that intent used to
    spend a use and the Bonus Action for nothing)."""
    handle, live = start([druid()], seed=1)
    _wild_shape(handle)
    assert [(e.spell_id, e.reason) for e in events(live, CastFailed)] == [("", "invalid_form")]
    assert (combatant(live, DRUID).bonus_action_available, _uses_spent(live)) == (True, 0)


def test_leaving_the_form_is_a_bonus_action_that_spends_no_use() -> None:
    """ "You can also leave the form early as a Bonus Action." The druid's own
    statistics come back, and the Temporary Hit Points it gained stay (only
    Polymorph's vanish)."""
    handle, live = start([druid()], seed=1, encounter=[_far_foe()])
    _wild_shape(handle, "giant-badger")
    _next_turn(handle)
    _wild_shape(handle)
    back = combatant(live, DRUID)
    assert _wild_shape_ends(live) == ["remove_ieffect"]
    assert (back.ac, back.strength, back.constitution) == (10, 10, 10)
    assert DRUID not in get_live(handle).transformations
    assert (_uses_spent(live), back.bonus_action_available, live.current_actor_id) == (
        1,
        False,
        DRUID,
    )
    assert live.tracked_temp_hp[DRUID] == 6


def test_using_wild_shape_again_changes_the_form() -> None:
    """ "...until you use Wild Shape again": the new form replaces the old one
    and costs another use."""
    handle, live = start([druid()], seed=1, encounter=[_far_foe()])
    _wild_shape(handle, "giant-badger")
    _next_turn(handle)
    _wild_shape(handle, "wolf")
    assert _wild_shape_ends(live) == ["remove_ieffect"]
    assert get_live(handle).transformations[DRUID].form_slug == "wolf"
    assert (combatant(live, DRUID).ac, _uses_spent(live)) == (12, 2)


def test_unconscious_ends_wild_shape() -> None:
    """46 damage spends the 6 Temporary Hit Points and all 40 Hit Points with
    nothing left over, so the druid falls Unconscious, which includes the
    Incapacitated condition."""
    handle, live = start([druid()], seed=1)
    _wild_shape(handle, "giant-badger")
    _emit(
        live,
        DamageApplied(target_id=DRUID, amount=46, damage_type="bludgeoning", is_overkill=False),
    )
    assert any(e.condition == "unconscious" for e in events(live, ConditionApplied))
    assert _wild_shape_ends(live) == ["incapacitated"]
    assert (combatant(live, DRUID).ac, DRUID in get_live(handle).transformations) == (10, False)


def test_hold_persons_paralysis_ends_wild_shape() -> None:
    """Paralyzed includes Incapacitated. The druid keeps its creature type (a
    Humanoid) in Beast form, so Hold Person can target it. Seed 1: the druid's
    Wisdom save rolls 5 against the Wizard 9's DC 16."""
    party = [druid(creature_type="humanoid"), wizard(initiative=15)]
    handle, live = start(party, seed=1, encounter=[_far_foe()])
    _wild_shape(handle, "giant-badger")
    act(handle, DRUID, intent_type="pass")
    act(
        handle,
        "char:wiz",
        intent_type="cast_spell",
        spell_id="hold-person",
        target_id=DRUID,
        slot_level=2,
    )
    assert any(c.condition == "paralyzed" for c in combatant(live, DRUID).conditions)
    assert _wild_shape_ends(live) == ["incapacitated"]


def test_an_instant_kill_ends_wild_shape() -> None:
    """ "...or die." 86 damage spends the 6 Temporary Hit Points and the 40 Hit
    Points with 40 left over — the druid's Hit Point maximum, so it dies
    outright (Massive Damage)."""
    handle, live = start([druid()], seed=1)
    _wild_shape(handle, "giant-badger")
    _emit(
        live,
        DamageApplied(target_id=DRUID, amount=86, damage_type="bludgeoning", is_overkill=True),
    )
    assert DRUID in live.dead_ids
    assert _wild_shape_ends(live) == ["source_dead"]


def test_a_wild_shaped_druid_cannot_cast_but_keeps_concentrating() -> None:
    """ "You can't cast spells, but shapeshifting doesn't break your
    Concentration or otherwise interfere with a spell you've already cast."
    The far foe never reaches the druid, so no damage tests its Concentration."""
    caster = druid(spells_known=["bless"], spell_slots={1: 2})
    handle, live = start([caster], seed=1, encounter=[_far_foe()])
    act(handle, DRUID, intent_type="cast_spell", spell_id="bless", target_id=DRUID)
    monster_turn(handle)
    _wild_shape(handle, "giant-badger")
    act(handle, DRUID, intent_type="cast_spell", spell_id="bless", target_id=DRUID)
    assert [e.reason for e in events(live, CastFailed)] == ["no_spellcasting"]
    assert live.spell_slots_by_entity[DRUID] == {1: 1}
    assert [entry[1] for entry in live.concentration_chain[DRUID]] == ["effect:blessed"]


def test_a_polymorphed_druid_cannot_wild_shape() -> None:
    """Polymorph replaces the target's game statistics, class features
    included, so the druid it holds has no Wild Shape: the intent is refused
    and the Polymorph stays."""
    handle, live = start([druid()], seed=1)
    wolf = _form("wolf")
    _apply_transform(
        live,
        DRUID,
        wolf,
        source="polymorph",
        effect=ActiveEffect(
            id="effect:polymorph",
            name="Polymorph",
            origin="cast:polymorph:mon:foe",
            target_id=DRUID,
            flags={"concentration": True, TRANSFORM_FORM_FLAG: "wolf"},
        ),
        temp_hp=wolf.hp,
    )
    _wild_shape(handle, "giant-badger")
    assert [e.reason for e in events(live, CastFailed)] == ["invalid_form"]
    assert get_live(handle).transformations[DRUID].source == "polymorph"
    assert (_uses_spent(live), combatant(live, DRUID).bonus_action_available) == (0, True)
