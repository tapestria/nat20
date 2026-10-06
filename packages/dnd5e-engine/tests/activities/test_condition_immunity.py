"""``is_condition_immune`` — the one condition-immunity predicate.

SRD 5.2 Immunity: "If you have Immunity to a damage type or a condition, it
doesn't affect you in any way." A creature is immune to a condition its stat
block or features list, and to one a condition it has grants: Petrified,
"Poison Immunity. You have Immunity to the Poisoned condition."
"""

from __future__ import annotations

from dnd5e_engine.activities.effects import is_condition_immune
from dnd5e_engine.types.combat import Combatant
from dnd5e_engine.types.conditions import ActiveCondition


def _creature(*held: str, immunities: tuple[str, ...] = ()) -> Combatant:
    return Combatant(
        entity_id="mon:statue",
        entity_type="Monster",
        name="Statue",
        initiative=1,
        hp_current=10,
        hp_max=10,
        condition_immunities=list(immunities),
        conditions=[
            ActiveCondition(condition=c, source_entity_id="implied:test", scope="combat")
            for c in held
        ],
    )


def test_a_listed_immunity_keeps_its_condition_off() -> None:
    ghost = _creature(immunities=("grappled", "prone"))
    assert is_condition_immune(ghost, "grappled")
    assert not is_condition_immune(ghost, "blinded")


def test_petrified_grants_immunity_to_poisoned_only() -> None:
    statue = _creature("petrified")
    assert is_condition_immune(statue, "poisoned")
    assert not is_condition_immune(statue, "prone")
    assert not is_condition_immune(_creature(), "poisoned")


def test_conditions_arriving_together_count() -> None:
    # One effect that both petrifies and poisons leaves its target Petrified only.
    imposed = {"petrified", "poisoned"}
    assert is_condition_immune(_creature(), "poisoned", imposed=imposed)
    assert not is_condition_immune(_creature(), "petrified", imposed=imposed)
    # A creature that can't be Petrified gains no immunity from one that never lands.
    swarm = _creature(immunities=("petrified",))
    assert not is_condition_immune(swarm, "poisoned", imposed=imposed)
