"""C22 — Magic Resistance (typed trait) ⇒ Advantage on saves against spells."""

from __future__ import annotations

import random

from dnd5e_srd_data.schema.monster import MonsterTraitMechanic

from dnd5e_engine.activities.context import ActivityResolutionContext
from dnd5e_engine.activities.save_primitive import roll_save
from dnd5e_engine.types.combat import Combatant


def _ctx(seed: int, *, spell_level: int | None, traits: list[MonsterTraitMechanic]):
    caster = Combatant(
        entity_id="c", entity_type="Character", name="C", initiative=10, hp_current=10, hp_max=10
    )
    target = Combatant(
        entity_id="t",
        entity_type="Monster",
        name="T",
        initiative=1,
        hp_current=10,
        hp_max=10,
        trait_mechanics=traits,
    )
    ctx = ActivityResolutionContext(
        rng=random.Random(seed),
        caster=caster,
        targets=[target],
        event_emitter=lambda e: None,
        caster_abilities={"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10},
        base_spell_level=spell_level,
    )
    return ctx, target


def test_magic_resistance_rolls_spell_saves_with_advantage_from_the_trait_source():
    ctx, target = _ctx(3, spell_level=3, traits=[MonsterTraitMechanic.MAGIC_RESISTANCE])
    roll = roll_save(ctx, target, "dex", 15)
    assert roll.mode == "advantage"
    assert roll.sources == ("trait",)
    # Two draws were consumed (advantage), and the kept die is the higher one.
    rng = random.Random(3)
    a, b = rng.randint(1, 20), rng.randint(1, 20)
    assert roll.natural == max(a, b)


def test_magic_resistance_is_inert_for_non_spell_saves():
    ctx, target = _ctx(3, spell_level=None, traits=[MonsterTraitMechanic.MAGIC_RESISTANCE])
    roll = roll_save(ctx, target, "dex", 15)
    assert roll.mode == "normal"
    assert roll.sources == ()
    assert roll.natural == random.Random(3).randint(1, 20)  # exactly one draw


def test_other_traits_do_not_grant_save_advantage():
    ctx, target = _ctx(3, spell_level=1, traits=[MonsterTraitMechanic.PACK_TACTICS])
    assert roll_save(ctx, target, "wis", 15).mode == "normal"


def test_cantrips_count_as_spells():
    ctx, target = _ctx(5, spell_level=0, traits=[MonsterTraitMechanic.MAGIC_RESISTANCE])
    assert roll_save(ctx, target, "dex", 15).mode == "advantage"
