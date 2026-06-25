"""Unit — the damage-modifier math in ``activities/apply.py:_apply_modifiers``.

``_apply_modifiers`` is an engine-internal helper (private name), so its math is
asserted here, in-package, where private access is legitimate. It applies
vulnerability (×2) → resistance (//2 floor) → immunity (⇒0) in Avrae order, and
honors the ``"all"`` wildcard in each set.

(Relocated from the host integration test, which now asserts only the public
combat behavior — the engine owns its internal math.)
"""

from dnd5e_engine.activities.apply import _apply_modifiers


def test_resistance_halves_floor():
    assert _apply_modifiers(20, "poison", {"poison"}, set(), set()) == 10
    # //2 floor, not round.
    assert _apply_modifiers(7, "poison", {"poison"}, set(), set()) == 3


def test_unresisted_type_passes_through():
    assert _apply_modifiers(20, "fire", {"poison"}, set(), set()) == 20


def test_vulnerability_doubles():
    assert _apply_modifiers(10, "fire", set(), set(), {"fire"}) == 20


def test_immunity_zeroes():
    assert _apply_modifiers(20, "poison", set(), {"poison"}, set()) == 0


def test_apply_order_vuln_then_resist_then_immune():
    # vuln ×2 → resist //2 nets back to the original amount.
    assert _apply_modifiers(20, "fire", {"fire"}, set(), {"fire"}) == 20
    # immunity wins regardless of vuln/resist.
    assert _apply_modifiers(20, "fire", {"fire"}, {"fire"}, {"fire"}) == 0


def test_all_wildcard_honored_per_set():
    assert _apply_modifiers(20, "poison", {"all"}, set(), set()) == 10
    assert _apply_modifiers(10, "fire", set(), set(), {"all"}) == 20
    assert _apply_modifiers(20, "cold", set(), {"all"}, set()) == 0
