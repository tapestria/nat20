"""Unit — engine-internal invariants of the PassiveEffect → ActiveEffect builder.

The ``_MODE_MAP`` int→str correspondence is engine-internal (private name), so
its structural pin lives here, in-package, where private access is legitimate.
The map's int keys are Foundry ``CONST.ACTIVE_EFFECT_MODES``; the str values
MUST be the ``ChangeMode`` Literal members in declared order (index == int key).

(Relocated from the host test ``backend/tests/combat/activities/test_effects_builder.py``,
which keeps the public-API assertions on ``passive_effect_to_active_effect``.)
"""

from dnd5e_engine.activities.effects import _MODE_MAP
from dnd5e_engine.types.effects import ChangeMode


def test_mode_map_matches_change_mode_literal_order():
    literal_members = list(ChangeMode.__args__)
    assert literal_members == ["custom", "multiply", "add", "downgrade", "upgrade", "override"]
    expected = {i: m for i, m in enumerate(literal_members)}
    assert expected == _MODE_MAP
