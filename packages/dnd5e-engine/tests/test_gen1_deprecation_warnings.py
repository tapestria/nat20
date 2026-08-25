"""0.4.0 deprecation contract for the legacy (Gen 1) surface — removed in 0.5.0.

See ``docs/migration/v0.3-to-v0.4.md`` for the per-symbol route.
"""

from __future__ import annotations

import importlib
import sys
import warnings

import pytest

GEN1_MODULES = [
    "dnd5e_engine.dispatch",
    "dnd5e_engine.event_dicts",
    "dnd5e_engine.types.dice",
    "dnd5e_engine.types.intent",
    "dnd5e_engine.rules.combat",
    "dnd5e_engine.rules.combat_data",
    "dnd5e_engine.rules.combat_helpers",
    "dnd5e_engine.rules.equipment",
    "dnd5e_engine.rules.gambits",
    "dnd5e_engine.rules.resolution",
    "dnd5e_engine.rules.spells",
]


@pytest.mark.parametrize("module", GEN1_MODULES)
def test_importing_a_gen1_module_warns(module: str) -> None:
    sys.modules.pop(module, None)
    with pytest.warns(DeprecationWarning, match="removed in dnd5e-engine 0.5.0"):
        importlib.import_module(module)


def test_top_level_action_type_access_warns() -> None:
    import dnd5e_engine

    with pytest.warns(DeprecationWarning, match="ActionType"):
        _ = dnd5e_engine.ActionType


@pytest.mark.parametrize("name", ["ActionType", "CombatOutcome", "DiceOutcome", "CombatNPC"])
def test_types_package_legacy_names_warn_on_access(name: str) -> None:
    import dnd5e_engine.types as t

    with pytest.warns(DeprecationWarning, match=name):
        _ = getattr(t, name)


def test_unknown_top_level_name_still_raises_attribute_error() -> None:
    import dnd5e_engine

    with pytest.raises(AttributeError):
        _ = dnd5e_engine.definitely_not_a_name


def test_gen2_top_level_names_do_not_warn() -> None:
    import dnd5e_engine

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        _ = (dnd5e_engine.start_combat, dnd5e_engine.CombatOutcome, dnd5e_engine.resolve_check)
