"""Pin the SRD hit / crit / miss classification of the attack resolver.

Carried over from the (now retired) cross-generation parity test: these are
the rules whose drift between the two former implementations motivated the
0.5.0 consolidation, so they stay pinned on the surviving path.
"""

from __future__ import annotations

import random

import pytest
from dnd5e_srd_data.loader import BundledAssetLoader
from dnd5e_srd_data.schema.common import AttackActivity

from dnd5e_engine.activities.attack import _resolve_hit_outcome
from dnd5e_engine.activities.d20 import AdvantageSources, roll_d20_test


@pytest.fixture(scope="module")
def attack() -> AttackActivity:
    longsword = BundledAssetLoader().get_weapon("longsword")
    assert longsword is not None
    activity = next(a for a in longsword.activities if a.kind == "attack")
    assert isinstance(activity, AttackActivity)
    return activity


def _kept(seed: int, mode: str) -> int:
    """The natural d20 an attack keeps, resolved through the shared primitive.

    ``resolve_attack`` builds typed ``AdvantageSources`` and calls
    ``roll_d20_test``; this mirrors that call with a single source of the
    requested kind, which is exactly what one advantage-granting flag or
    condition produces.
    """
    sources = AdvantageSources(
        advantage=("flag",) if mode == "advantage" else (),
        disadvantage=("flag",) if mode == "disadvantage" else (),
    )
    return roll_d20_test(random.Random(seed), 0, sources).kept


def test_natural_one_always_misses_even_with_a_huge_bonus(attack: AttackActivity) -> None:
    assert _resolve_hit_outcome(1, 1 + 50, 10, attack) == (False, False)


def test_natural_twenty_always_crits_even_against_impossible_ac(attack: AttackActivity) -> None:
    assert _resolve_hit_outcome(20, 20, 99, attack) == (True, True)


def test_meeting_the_ac_exactly_is_a_hit(attack: AttackActivity) -> None:
    assert _resolve_hit_outcome(10, 15, 15, attack) == (False, True)


def test_falling_one_short_of_the_ac_is_a_miss(attack: AttackActivity) -> None:
    assert _resolve_hit_outcome(10, 14, 15, attack) == (False, False)


@pytest.mark.parametrize("seed", range(32))
def test_advantage_keeps_the_higher_and_disadvantage_the_lower_die(seed: int) -> None:
    rng = random.Random(seed)
    a, b = rng.randint(1, 20), rng.randint(1, 20)
    assert _kept(seed, "advantage") == max(a, b)
    assert _kept(seed, "disadvantage") == min(a, b)
    assert _kept(seed, "normal") == a


def test_disadvantage_does_not_crit_on_the_discarded_die(attack: AttackActivity) -> None:
    # Find a seed whose two dice are (20, x<20): the kept die under disadvantage
    # must not be the discarded 20.
    for seed in range(500):
        rng = random.Random(seed)
        a, b = rng.randint(1, 20), rng.randint(1, 20)
        if 20 in (a, b) and min(a, b) < 20:
            natural = _kept(seed, "disadvantage")
            assert natural == min(a, b)
            assert _resolve_hit_outcome(natural, natural, 99, attack)[0] is False
            return
    pytest.fail("no seed with a discarded 20 in 500 tries")
