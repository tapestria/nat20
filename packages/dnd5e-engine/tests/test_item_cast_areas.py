"""An item whose one resolved activity casts a spell targets as that spell.

SRD 5.2 Necklace of Fireballs: "You can take a Magic action to detach a bead
and throw it up to 60 feet away. When it reaches the end of its trajectory,
the bead detonates as a level 3 Fireball (save DC 15)."

SRD 5.2 Wand of Fireballs: "you can expend no more than 3 charges to cast
Fireball (save DC 15) from it. For 1 charge, you cast the level 3 version of
the spell."

SRD 5.2 Fireball: "Each creature in a 20-foot-radius Sphere centered on that
point makes a Dexterity saving throw."

SRD 5.2 Wand of Magic Missiles: "you can expend no more than 3 charges to cast
Magic Missile from it. For 1 charge, you cast the level 1 version of the spell.
You can increase the spell's level by 1 for each additional charge you
expend."

SRD 5.2 Magic Missile: "You create three glowing darts of magical force. Each
dart strikes a creature of your choice that you can see within range ... you
can direct them to hit one creature or several. Using a Higher-Level Spell
Slot. The spell creates one more dart for each spell slot level above 1."
"""

from __future__ import annotations

from collections import Counter

from dnd5e_srd_data.loader import BundledAssetLoader

from dnd5e_engine import PlayerIntent
from dnd5e_engine.areas import area_activity
from dnd5e_engine.events import AreaTargeted, CastFailed, DamageApplied, SaveRolled
from dnd5e_engine.orchestrator import _area_plan, _item_charges_spent
from dnd5e_engine.spatial import cell_id
from tests.c20_support import act, combatant, events, foe, pc, start

_HERO = "char:hero"


def _three_foes():
    """Two foes 5 feet apart at 5,5 and 6,5, and a third 25 feet from 5,5."""
    return [
        foe(entity_id="mon:a", zone_id=cell_id(5, 5), initiative=3),
        foe(entity_id="mon:b", zone_id=cell_id(6, 5), initiative=2),
        foe(entity_id="mon:c", zone_id=cell_id(0, 5), initiative=1),
    ]


def _use(handle, item_id: str, **intent) -> None:
    act(handle, _HERO, intent_type="use_item", item_id=item_id, **intent)


def _fireball_lands_on_a_and_b(live, item_id: str) -> None:
    [area] = events(live, AreaTargeted)
    assert (area.source_id, area.shape, area.size_ft, area.origin) == (
        item_id,
        "sphere",
        20,
        cell_id(5, 5),
    )
    assert sorted(area.affected_ids) == ["mon:a", "mon:b"]
    assert sorted(e.target_id for e in events(live, SaveRolled)) == ["mon:a", "mon:b"]
    assert {e.target_id for e in events(live, DamageApplied)} == {"mon:a", "mon:b"}
    assert combatant(live, "mon:c").hp_current == combatant(live, "mon:c").hp_max


def test_a_necklace_bead_detonates_as_a_fireball_sphere() -> None:
    handle, live = start([pc()], seed=3, encounter=_three_foes())
    _use(handle, "necklace-of-fireballs", target_id="mon:a")
    _fireball_lands_on_a_and_b(live, "necklace-of-fireballs")


def test_a_wand_of_fireballs_casts_a_fireball_sphere_for_one_charge() -> None:
    handle, live = start([pc()], seed=3, encounter=_three_foes())
    _use(handle, "wand-of-fireballs", target_id="mon:a")
    _fireball_lands_on_a_and_b(live, "wand-of-fireballs")
    assert _item_charges_spent(live, _HERO, "wand-of-fireballs") == 1


def test_an_upcast_wand_of_fireballs_still_places_its_sphere() -> None:
    handle, live = start([pc()], seed=3, encounter=_three_foes())
    _use(handle, "wand-of-fireballs", target_id="mon:a", charges_to_spend=3)
    _fireball_lands_on_a_and_b(live, "wand-of-fireballs")
    assert _item_charges_spent(live, _HERO, "wand-of-fireballs") == 3


def _darts(live) -> Counter[str]:
    return Counter(e.target_id for e in events(live, DamageApplied))


def test_three_named_creatures_each_take_one_dart() -> None:
    handle, live = start([pc()], seed=3, encounter=_three_foes())
    _use(handle, "wand-of-magic-missiles", target_ids=["mon:a", "mon:b", "mon:c"])
    assert _darts(live) == Counter({"mon:a": 1, "mon:b": 1, "mon:c": 1})
    assert events(live, AreaTargeted) == []


def test_a_lone_target_takes_all_three_darts() -> None:
    handle, live = start([pc()], seed=3, encounter=_three_foes())
    _use(handle, "wand-of-magic-missiles", target_id="mon:a")
    assert _darts(live) == Counter({"mon:a": 3})


def test_each_extra_charge_adds_a_dart() -> None:
    handle, live = start([pc()], seed=3, encounter=_three_foes())
    _use(handle, "wand-of-magic-missiles", target_id="mon:b", charges_to_spend=3)
    assert _darts(live) == Counter({"mon:b": 5})
    assert _item_charges_spent(live, _HERO, "wand-of-magic-missiles") == 3


def test_a_robe_star_casts_the_level_5_magic_missile() -> None:
    """SRD 5.2 Robe of Stars: "you can take a Magic action to remove one of
    the stars and expend it to cast the level 5 version of Magic Missile":
    seven darts, all at a lone target."""
    handle, live = start([pc()], seed=3, encounter=_three_foes())
    _use(handle, "robe-of-stars", target_id="mon:a")
    assert _darts(live) == Counter({"mon:a": 7})


def test_an_upcast_wand_splits_its_darts_across_named_creatures() -> None:
    handle, live = start([pc()], seed=3, encounter=_three_foes())
    _use(
        handle,
        "wand-of-magic-missiles",
        target_ids=["mon:a", "mon:b", "mon:c", "mon:a"],
        charges_to_spend=2,
    )
    assert _darts(live) == Counter({"mon:a": 2, "mon:b": 1, "mon:c": 1})


def test_more_named_creatures_than_darts_is_refused_with_no_charge_spent() -> None:
    handle, live = start(
        [pc()],
        seed=3,
        encounter=[*_three_foes(), foe(entity_id="mon:d", zone_id=cell_id(9, 9), initiative=0)],
    )
    _use(handle, "wand-of-magic-missiles", target_ids=["mon:a", "mon:b", "mon:c", "mon:d"])
    assert [e.reason for e in events(live, CastFailed)] == ["target_invalid"]
    assert events(live, DamageApplied) == []
    assert _item_charges_spent(live, _HERO, "wand-of-magic-missiles") == 0


def test_a_multi_activity_item_with_no_activity_chosen_never_places_an_area() -> None:
    """The Horn of Blasting's blast, object damage, explosion roll and
    misfire damage are alternatives and none is charged, so a use naming no
    ``activity_id`` resolves all four and is ambiguous: no area, although its
    first templated activity (the blast's 30-foot Cone) would place one.
    Naming one cast on the Hat of Many Spells (its Fireball) is not
    ambiguous and places that spell's sphere."""
    loader = BundledAssetLoader()
    horn = loader.get_item("horn-of-blasting")
    hat = loader.get_item("hat-of-many-spells")
    assert horn is not None
    assert hat is not None
    unchosen = PlayerIntent(intent_type="use_item", item_id=horn.slug, target_id="mon:a")
    blast = area_activity(horn.activities)
    assert blast is not None
    assert blast.id == "FMTcQOb5MZKBohdN"
    assert not any(a.kind == "attack" for a in horn.activities)
    assert _area_plan(unchosen, list(horn.activities)) is None
    fireball = [a for a in hat.activities if a.id == "1Oov0JtLLqUAI5g2"]
    chosen = PlayerIntent(
        intent_type="use_item",
        item_id=hat.slug,
        activity_id="1Oov0JtLLqUAI5g2",
        target_id="mon:a",
    )
    plan = _area_plan(chosen, fireball)
    assert plan is not None
    assert plan.template is not None
    assert (plan.template.shape, plan.template.size_ft) == ("sphere", 20)


def test_a_chosen_fireball_on_a_multi_activity_item_places_its_sphere() -> None:
    handle, live = start([pc()], seed=3, encounter=_three_foes())
    _use(handle, "hat-of-many-spells", target_id="mon:a", activity_id="1Oov0JtLLqUAI5g2")
    _fireball_lands_on_a_and_b(live, "hat-of-many-spells")


def test_a_single_target_item_cast_resolves_as_before() -> None:
    """The Circlet of Blasting's Scorching Ray is an attack: one creature,
    the same seeded log as before item casts placed areas."""
    handle, live = start(
        [pc()],
        seed=5,
        encounter=[
            foe(entity_id="mon:a", zone_id=cell_id(3, 0)),
            foe(entity_id="mon:b", zone_id=cell_id(4, 0), initiative=2),
        ],
    )
    before = len(live.event_log)
    _use(handle, "circlet-of-blasting", target_id="mon:a")
    assert [e.model_dump() for e in live.event_log[before:]] == [
        {
            "type": "intent_submitted",
            "actor_id": "char:hero",
            "intent_type": "use_item",
            "spell_id": None,
            "target_id": "mon:a",
            "item_id": "circlet-of-blasting",
        },
        {
            "type": "attack_rolled",
            "attacker_id": "char:hero",
            "target_id": "mon:a",
            "roll_total": 25,
            "advantage": "normal",
            "is_crit": True,
            "is_hit": True,
            "is_opportunity_attack": False,
            "natural": 20,
            "modifier": 5,
            "sources": [],
            "advantage_sources": [],
            "disadvantage_sources": [],
        },
        {
            "type": "damage_applied",
            "target_id": "mon:a",
            "amount": 18,
            "damage_type": "fire",
            "is_overkill": False,
            "source_id": None,
            "is_crit": True,
        },
        {"type": "turn_phase", "actor_id": "char:hero", "phase": "turn_end", "round_number": 1},
        {"type": "turn_ended", "actor_id": "char:hero"},
        {"type": "turn_started", "actor_id": "mon:b"},
        {"type": "turn_phase", "actor_id": "mon:b", "phase": "turn_start", "round_number": 1},
    ]
