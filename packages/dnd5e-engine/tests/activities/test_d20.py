"""F2a — the unified SRD 5.2 D20 Test primitive."""

import random

from dnd5e_engine.activities.d20 import AdvantageSources, resolve_mode, roll_d20_test


def test_any_advantage_and_any_disadvantage_cancel():  # SRD 5.2 "Advantage and Disadvantage"
    assert resolve_mode(AdvantageSources(("flag", "condition:target"), ("cover",))) == "normal"


def test_normal_mode_consumes_exactly_one_draw():
    a, b = random.Random(3), random.Random(3)
    r = roll_d20_test(a, 5, AdvantageSources((), ()))
    assert r.first == b.randint(1, 20)
    assert r.kept == r.first  # normal mode: the only draw IS the kept die
    assert r.total == r.kept + 5
    assert a.random() == b.random()


def test_advantage_keeps_higher_of_two_draws():
    a, b = random.Random(3), random.Random(3)
    r = roll_d20_test(a, 0, AdvantageSources(("flag",), ()))
    first, second = b.randint(1, 20), b.randint(1, 20)
    assert r.kept == max(first, second)
    # ``first`` is the FIRST draw, which under advantage may be the discarded
    # one — the field is deliberately not named ``natural`` (see D20Result).
    assert r.first == first
    assert r.mode == "advantage"


def test_disadvantage_keeps_lower_of_two_draws():
    a, b = random.Random(7), random.Random(7)
    r = roll_d20_test(a, 0, AdvantageSources((), ("condition:attacker",)))
    assert r.kept == min(b.randint(1, 20), b.randint(1, 20))
    assert r.mode == "disadvantage"


def test_forced_natural_bypasses_rng():
    a = random.Random(1)
    assert roll_d20_test(a, 2, AdvantageSources(("flag",), ()), forced_natural=17).total == 19


def test_forced_natural_reports_the_same_value_as_first_and_kept():
    r = roll_d20_test(random.Random(1), 0, AdvantageSources(("flag",), ()), forced_natural=17)
    assert r.first == r.kept == 17


def test_forced_natural_consumes_zero_draws():
    a, b = random.Random(1), random.Random(1)
    roll_d20_test(a, 0, AdvantageSources((), ()), forced_natural=17)
    assert a.random() == b.random()


def test_result_carries_typed_sources():
    r = roll_d20_test(random.Random(3), 0, AdvantageSources(("flag", "help"), ()))
    assert set(r.sources) == {"flag", "help"}
