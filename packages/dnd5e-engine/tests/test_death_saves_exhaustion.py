"""SRD 5.2 Exhaustion on the death-save path.

A Death Saving Throw *is* a saving throw, hence a D20 Test, so the flat
``-2 x Exhaustion level`` penalty applies to it (rules glossary, Exhaustion).
The penalty rides the TOTAL only — the natural 1 / natural 20 special outcomes
still read the KEPT die — and it never adds a draw.
"""

from __future__ import annotations

import random

from dnd5e_engine.death_saves import roll_death_save
from dnd5e_engine.events import DeathSaveRolled
from dnd5e_engine.types.combat import Combatant
from dnd5e_engine.types.conditions import ActiveCondition


def _dying(*, exhaustion_level: int | None) -> Combatant:
    conds = (
        [
            ActiveCondition(
                condition="exhaustion",
                source_entity_id="implied:effect",
                scope="combat",
                exhaustion_level=exhaustion_level,
            )
        ]
        if exhaustion_level
        else []
    )
    return Combatant(
        entity_id="char:pc",
        entity_type="Character",
        name="PC",
        initiative=1,
        hp_current=0,
        hp_max=10,
        conditions=conds,
    )


def test_death_save_total_is_reduced_by_two_per_exhaustion_level() -> None:
    plain = roll_death_save(_dying(exhaustion_level=None), random.Random(3))
    tired = roll_death_save(_dying(exhaustion_level=2), random.Random(3))
    p = next(e for e in plain.events if isinstance(e, DeathSaveRolled))
    t = next(e for e in tired.events if isinstance(e, DeathSaveRolled))
    assert t.roll_total == p.roll_total - 4


def test_death_save_still_consumes_one_draw() -> None:
    rng = random.Random(3)
    roll_death_save(_dying(exhaustion_level=1), rng)
    assert rng.getstate() == (lambda r: (r.randint(1, 20), r.getstate())[1])(random.Random(3))
