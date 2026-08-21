from nat20_bridge.slots import slots_for


def test_full_caster_landmarks() -> None:
    assert slots_for("full", 1) == {1: 2}
    assert slots_for("full", 3) == {1: 4, 2: 2}
    assert slots_for("full", 5) == {1: 4, 2: 3, 3: 2}
    assert slots_for("full", 20) == {1: 4, 2: 3, 3: 3, 4: 3, 5: 3, 6: 2, 7: 2, 8: 1, 9: 1}


def test_half_caster_landmarks() -> None:
    assert slots_for("half", 1) == {}
    assert slots_for("half", 2) == {1: 2}
    assert slots_for("half", 5) == {1: 4, 2: 2}


def test_pact_magic_landmarks() -> None:
    assert slots_for("pact", 1) == {1: 1}
    assert slots_for("pact", 5) == {3: 2}
    assert slots_for("pact", 17) == {5: 4}


def test_none_and_unknown() -> None:
    assert slots_for("none", 20) == {}
    assert slots_for("martial-nonsense", 20) == {}


def test_level_bounds() -> None:
    assert slots_for("full", 0) == {}
    assert slots_for("full", -1) == {}
    assert slots_for("full", 25) == slots_for("full", 20)
