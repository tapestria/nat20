"""Stat-block commands (C21): an ``attack`` naming ``stat_block_action_id`` is
one swing of an attack action on the actor's current stat block — its form's
while it is transformed. SRD 5.2 Wild Shape: "Your game statistics are replaced
by the Beast's stat block"; Polymorph: "The target's game statistics are
replaced by the stat block of the chosen Beast". The swing is rolled at the
stat block's own numbers — the Wolf: "Bite. Melee Attack Roll: +4, reach 5 ft.
5 (1d6 + 2) Piercing damage."

The transform draws nothing, initiatives are explicit and no reaction is armed,
so each seeded test's first draws are the swing's own d20 and damage dice.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from dnd5e_srd_data.loader import BundledAssetLoader
from dnd5e_srd_data.schema.common import AttackActivity
from dnd5e_srd_data.schema.monster import Monster

from dnd5e_engine import CombatHandle, get_live
from dnd5e_engine.activities.conjuration import TRANSFORM_FORM_FLAG, TransformSource
from dnd5e_engine.events import AttackFailed, AttackRolled, DamageApplied
from dnd5e_engine.lib_loader import get_lib_loader, set_lib_loader_for_tests
from dnd5e_engine.orchestrator import _apply_transform, _LiveCombat
from dnd5e_engine.spatial import cell_id
from dnd5e_engine.types.effects import ActiveEffect
from tests.c21_support import act, combatant, events, foe, monster_turn, pc, start

_SCORES = {
    "str": "strength",
    "dex": "dexterity",
    "con": "constitution",
    "int": "intelligence",
    "wis": "wisdom",
    "cha": "charisma",
}


@pytest.fixture(autouse=True)
def _bundled_loader() -> Iterator[None]:
    set_lib_loader_for_tests(BundledAssetLoader())
    yield
    set_lib_loader_for_tests(None)


def _form(slug: str) -> Monster:
    form = get_lib_loader().get_monster(slug)
    assert form is not None, slug
    return form


def _shape(
    live: _LiveCombat,
    entity_id: str,
    slug: str,
    *,
    source: TransformSource = "wild-shape",
    caster_id: str | None = None,
) -> None:
    """Transform ``entity_id`` into ``slug`` as Wild Shape does to its druid, or
    as a Polymorph cast by ``caster_id`` does to its target."""
    form = _form(slug)
    flags: dict[str, Any] = {TRANSFORM_FORM_FLAG: slug}
    if source == "polymorph":
        flags["concentration"] = True
    _apply_transform(
        live,
        entity_id,
        form,
        source=source,
        effect=ActiveEffect(
            id=f"effect:{source}",
            name="Polymorph" if source == "polymorph" else "Wild Shape",
            origin=f"cast:{source}:{caster_id or entity_id}",
            target_id=entity_id,
            flags=flags,
        ),
        temp_hp=form.hp if source == "polymorph" else 1,
    )


def _swing(handle: CombatHandle, action: str, **extra: Any) -> None:
    act(
        handle,
        "char:hero",
        intent_type="attack",
        stat_block_action_id=action,
        target_id="mon:foe",
        **extra,
    )


def test_a_wolf_form_bites_at_its_stat_block_numbers() -> None:
    """STR 14 (+2) and the Wolf's Proficiency Bonus (+2) make the +4. The Bite's
    base damage gets the +2 back: Foundry adds ``@mod`` to a weapon's base
    damage as it rolls it. Seed 11: d20 15 → 19; d6 5 → 7."""
    handle, live = start([pc()], seed=11)
    _shape(live, "char:hero", "wolf")
    _swing(handle, "bite")
    (roll,) = events(live, AttackRolled)
    (damage,) = events(live, DamageApplied)
    assert (roll.natural, roll.modifier, roll.roll_total, roll.advantage) == (15, 4, 19, "normal")
    assert (damage.target_id, damage.amount, damage.damage_type) == ("mon:foe", 7, "piercing")


def test_a_giant_badger_form_bites_for_2d4_plus_1() -> None:
    """Giant Badger: "Bite. Melee Attack Roll: +3, reach 5 ft. 6 (2d4 + 1)
    Piercing damage." STR 13 (+1) + PB 2. Seed 11: d20 15 → 18; 2d4 4 + 4,
    plus 1 → 9."""
    handle, live = start([pc()], seed=11)
    _shape(live, "char:hero", "giant-badger")
    _swing(handle, "bite")
    (roll,) = events(live, AttackRolled)
    (damage,) = events(live, DamageApplied)
    assert (roll.modifier, roll.roll_total, damage.amount) == (3, 18, 9)


def test_the_wolf_forms_pack_tactics_comes_with_its_stat_block() -> None:
    """Wolf: "Pack Tactics. The wolf has Advantage on attack rolls against a
    creature if at least one of the wolf's allies is within 5 feet of the
    creature and the ally doesn't have the Incapacitated condition." The ally
    stands 5 feet from the foe and acts after the hero."""
    ally = pc("char:ally", initiative=15, zone_id=cell_id(2, 0))
    handle, live = start([pc(), ally], seed=11)
    _shape(live, "char:hero", "wolf")
    _swing(handle, "bite")
    (roll,) = events(live, AttackRolled)
    assert roll.advantage == "advantage"
    assert "trait" in roll.advantage_sources


@pytest.mark.parametrize(("ally_col", "advantage"), [(2, "advantage"), (5, "normal")])
def test_a_host_driven_attacker_gets_its_pack_tactics(ally_col: int, advantage: str) -> None:
    """Tough: "Pack Tactics. The tough has Advantage on an attack roll against a
    creature if at least one of the tough's allies is within 5 feet of the
    creature and the ally doesn't have the Incapacitated condition." The trait
    holds whichever entry point drives its bearer: a Tough swinging its Mace
    through ``submit_player_intent`` rolls with Advantage, one more d20, while
    its ally stands 5 feet from the target, and normally with the ally 20 feet
    away. Seed 1: d20s 5 and 19."""
    tough = {"monster_template_slug": "tough"}
    handle, live = start(
        [pc(initiative=1, zone_id=cell_id(1, 0))],
        seed=1,
        encounter=[
            foe(entity_id="mon:tough", initiative=20, zone_id=cell_id(0, 0), **tough),
            foe(entity_id="mon:ally", initiative=19, zone_id=cell_id(ally_col, 0), **tough),
        ],
    )
    act(handle, "mon:tough", intent_type="attack", target_id="char:hero", weapon_id="mace")
    (roll,) = events(live, AttackRolled)
    assert (roll.attacker_id, roll.advantage) == ("mon:tough", advantage)
    assert roll.advantage_sources == (["trait"] if advantage == "advantage" else [])
    assert roll.natural == (19 if advantage == "advantage" else 5)


def test_a_form_taken_this_turn_swings_its_multiattack_count() -> None:
    """Black Bear: "Multiattack. The bear makes two Rend attacks." A creature
    that changes shape before it attacks (Wild Shape is a Bonus Action) takes
    the Attack action with its form's count. The host picks each swing, and a
    multi-attack actor keeps its turn until it passes."""
    handle, live = start([pc()], seed=1)
    _shape(live, "char:hero", "black-bear")
    _swing(handle, "rend")
    assert (get_live(handle).turn.attacks_remaining, live.current_actor_id) == (1, "char:hero")
    _swing(handle, "rend")
    assert (get_live(handle).turn.attacks_remaining, live.current_actor_id) == (0, "char:hero")
    _swing(handle, "rend")
    assert len(events(live, AttackRolled)) == 2
    assert [e.reason for e in events(live, AttackFailed)] == ["no_action_economy"]


@pytest.mark.parametrize(
    ("fields", "source", "slug", "count"),
    [
        ({}, "wild-shape", "black-bear", 2),
        ({}, "wild-shape", "brown-bear", 2),
        ({"class_slug": "fighter", "character_level": 5}, "wild-shape", "wolf", 2),
        ({"class_slug": "fighter", "character_level": 5}, "polymorph", "wolf", 1),
    ],
    ids=["two-rends", "bite-and-claw", "wild-shape-keeps-extra-attack", "polymorph-replaces-it"],
)
def test_the_attack_action_takes_the_forms_count(
    fields: dict[str, Any], source: TransformSource, slug: str, count: int
) -> None:
    """At the next turn start: the form's Multiattack count ("one Bite attack and
    one Claw attack" is two). Wild Shape keeps class features, so a Fighter 5's
    Extra Attack still gives two swings in a one-attack form; Polymorph
    replaces the game statistics, class features included."""
    handle, live = start([pc(**fields)], seed=1)
    _shape(live, "char:hero", slug, source=source)
    act(handle, "char:hero", intent_type="pass")
    monster_turn(handle)
    assert (live.current_actor_id, get_live(handle).turn.attacks_remaining) == ("char:hero", count)


@pytest.mark.parametrize(
    ("form", "intent"),
    [
        ("wolf", {"stat_block_action_id": "claw"}),
        ("black-bear", {"stat_block_action_id": "multiattack"}),
        ("lion", {"stat_block_action_id": "roar"}),
        ("wolf", {"stat_block_action_id": "bite", "spell_id": "spiritual-weapon"}),
        (None, {"stat_block_action_id": "bite"}),
    ],
    ids=["not-on-the-stat-block", "multiattack", "save-action", "with-a-spell", "no-stat-block"],
)
def test_an_uncommandable_swing_is_refused_before_anything_is_spent(
    form: str | None, intent: dict[str, Any]
) -> None:
    """Only an attack action on the actor's current stat block can be commanded
    — never the Multiattack itself (each swing is its own intent) or a save
    action such as the Lion's Roar."""
    handle, live = start([pc()], seed=1)
    if form is not None:
        _shape(live, "char:hero", form)
    act(handle, "char:hero", intent_type="attack", target_id="mon:foe", **intent)
    hero = combatant(live)
    assert [e.reason for e in events(live, AttackFailed)] == ["action_unavailable"]
    assert (hero.action_available, hero.attack_action_engaged) == (True, False)
    assert (live.current_actor_id, events(live, AttackRolled)) == ("char:hero", [])


def test_a_command_that_also_names_a_weapon_is_refused() -> None:
    """One swing is one attack: a stat-block action or a weapon, never both. A
    template monster driven through ``submit_player_intent`` has a stat block
    without being transformed."""
    wolf = foe(
        entity_id="mon:wolf", initiative=30, monster_template_slug="wolf", zone_id=cell_id(0, 1)
    )
    handle, live = start([pc()], seed=1, encounter=[wolf])
    act(
        handle,
        "mon:wolf",
        intent_type="attack",
        stat_block_action_id="bite",
        weapon_id="dagger",
        target_id="char:hero",
    )
    assert [e.reason for e in events(live, AttackFailed)] == ["action_unavailable"]
    assert (combatant(live, "mon:wolf").action_available, events(live, AttackRolled)) == (True, [])


def test_a_target_beyond_the_forms_reach_is_refused() -> None:
    """The Wolf's Bite has "reach 5 ft."; a foe 10 feet away is out of range."""
    handle, live = start([pc()], seed=1, encounter=[foe(zone_id=cell_id(2, 0))])
    _shape(live, "char:hero", "wolf")
    _swing(handle, "bite")
    assert [e.reason for e in events(live, AttackFailed)] == ["out_of_range"]
    assert combatant(live).action_available


def test_a_polymorphed_monster_attacks_with_its_form_on_its_turn() -> None:
    """A monster's own turn picks from its current stat block, at the form's
    real numbers: the Tough polymorphed into a Wolf bites at +4 for 1d6 + 2.
    Seed 11: d20 15 → 19 against AC 10; d6 5 → 7."""
    handle, live = start([pc()], seed=11, encounter=[foe(monster_template_slug="tough")])
    _shape(live, "mon:foe", "wolf", source="polymorph", caster_id="char:hero")
    act(handle, "char:hero", intent_type="pass")
    monster_turn(handle)
    (roll,) = events(live, AttackRolled)
    (damage,) = events(live, DamageApplied)
    assert (roll.attacker_id, roll.modifier, roll.roll_total) == ("mon:foe", 4, 19)
    assert (damage.target_id, damage.amount, damage.damage_type) == ("char:hero", 7, "piercing")


def test_an_untransformed_template_monster_keeps_the_legacy_magnitudes() -> None:
    """Only a transformed creature gets its stat block's real magnitudes: a
    template monster still rolls to hit at its spec's ``attack_bonus`` (+0 by
    default) and adds no ability modifier to its damage (BACKLOG). Seed 11: the
    Tough's Mace, d20 15 → 15 against AC 10; d6 5 → 5."""
    handle, live = start([pc()], seed=11, encounter=[foe(monster_template_slug="tough")])
    act(handle, "char:hero", intent_type="pass")
    monster_turn(handle)
    (roll,) = events(live, AttackRolled)
    (damage,) = events(live, DamageApplied)
    assert (roll.modifier, roll.roll_total, damage.amount) == (0, 15, 5)


def _beast_attacks() -> list[tuple[str, str]]:
    """Every attack action of every corpus Beast but a summon stat block (Giant
    Insect's formulas read its summoner's spell level, ``@flags.dnd5e.summon``)."""
    loader = BundledAssetLoader()
    rows: list[tuple[str, str]] = []
    for slug in loader.list_slugs("monsters"):
        monster = loader.get_monster(slug)
        if monster is None or monster.creature_type != "beast":
            continue
        if "@flags.dnd5e.summon" in monster.model_dump_json():
            continue
        rows.extend(
            (slug, action.slug)
            for action in monster.actions
            if any(isinstance(a, AttackActivity) for a in action.activities)
        )
    return rows


@pytest.mark.parametrize(("slug", "action"), _beast_attacks())
def test_every_beast_attack_resolves_from_a_transformed_actor(slug: str, action: str) -> None:
    """Every Beast attack a form can make resolves without raising, rolled at the
    governing modifier (the attack's own ability, else DEX for a ranged attack
    and STR otherwise) plus the form's Proficiency Bonus."""
    handle, live = start([pc()], seed=1)
    _shape(live, "char:hero", slug)
    form = _form(slug)
    attack = next(
        a
        for a in next(x for x in form.actions if x.slug == action).activities
        if isinstance(a, AttackActivity)
    )
    assert not attack.attack.flat
    assert not attack.attack.bonus
    ability = attack.attack.ability or ("dex" if attack.attack.type.value == "ranged" else "str")
    score = getattr(combatant(live), _SCORES[ability])
    _swing(handle, action)
    (roll,) = [e for e in events(live, AttackRolled) if e.attacker_id == "char:hero"]
    assert roll.modifier == (score - 10) // 2 + form.proficiency_bonus
