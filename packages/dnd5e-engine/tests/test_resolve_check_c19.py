"""CheckSpec: Jack of All Trades, Reliable Talent, and the kept die (C19)."""

from __future__ import annotations

import random
from typing import Any

from dnd5e_engine.check import CheckSpec, resolve_check


def _spec(**changes: Any) -> CheckSpec:
    fields: dict[str, Any] = {
        "kind": "skill",
        "skill": "arcana",
        "ability_scores": {"intelligence": 12},
        "proficient_skills": (),
        "proficient_saves": (),
        "proficiency_bonus": 3,
        "rng": random.Random(1),
    }
    fields.update(changes)
    return CheckSpec(**fields)


def _seed(predicate) -> int:  # first seed whose draws satisfy ``predicate``
    return next(s for s in range(500) if predicate(random.Random(s)))


def test_jack_of_all_trades_adds_half_the_bonus_to_an_unproficient_skill() -> None:
    assert (
        resolve_check(_spec(jack_of_all_trades=True)).modifier - resolve_check(_spec()).modifier
        == 1
    )


def test_jack_of_all_trades_never_stacks_with_proficiency() -> None:
    proficient = {"proficient_skills": ("arcana",)}
    assert (
        resolve_check(_spec(**proficient, jack_of_all_trades=True)).modifier
        == resolve_check(_spec(**proficient)).modifier
    )


def test_jack_of_all_trades_leaves_plain_ability_checks_alone() -> None:
    plain = {"kind": "ability", "skill": None, "ability": "intelligence"}
    assert (
        resolve_check(_spec(**plain, jack_of_all_trades=True)).modifier
        == resolve_check(_spec(**plain)).modifier
    )


def test_reliable_talent_treats_a_low_proficient_roll_as_10() -> None:
    seed = _seed(lambda r: r.randint(1, 20) <= 9)
    plain = resolve_check(_spec(proficient_skills=("arcana",), rng=random.Random(seed)))
    reliable = resolve_check(
        _spec(proficient_skills=("arcana",), rng=random.Random(seed), reliable_talent=True)
    )
    assert plain.natural_roll <= 9
    assert reliable.natural_roll == 10
    assert reliable.roll_total == 10 + plain.modifier


def test_reliable_talent_needs_the_skill_proficiency() -> None:
    seed = _seed(lambda r: r.randint(1, 20) <= 9)
    plain = resolve_check(_spec(rng=random.Random(seed)))
    reliable = resolve_check(_spec(rng=random.Random(seed), reliable_talent=True))
    assert reliable.natural_roll == plain.natural_roll <= 9


def test_natural_roll_is_the_kept_die_under_advantage() -> None:
    seed = _seed(lambda r: r.randint(1, 20) < r.randint(1, 20))
    draws = random.Random(seed)
    first, second = draws.randint(1, 20), draws.randint(1, 20)
    result = resolve_check(_spec(rng=random.Random(seed), advantage=True))
    assert result.natural_roll == max(first, second) == second
    assert result.modifier == 1  # INT 12, not proficient
    assert result.roll_total == result.natural_roll + result.modifier
