"""The supported engine (Gen 2) must import nothing from the deprecated Gen 1
surface, so ``import dnd5e_engine`` + orchestrator use never triggers a
``DeprecationWarning`` and the legacy modules can be deleted without touching
the supported ones.
"""

from __future__ import annotations

import ast
import subprocess
import sys

GEN1 = [
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
    "dnd5e_engine.rules._parsing",
    "dnd5e_engine.rules._class_meta",
]

GEN2_ENTRY = (
    "import dnd5e_engine, dnd5e_engine.orchestrator, dnd5e_engine.death_saves, "
    "dnd5e_engine.check, dnd5e_engine.rest, dnd5e_engine.views, dnd5e_engine.testing, "
    "dnd5e_engine.activities.resolver, dnd5e_engine.activities.build_context; "
    "import sys; print(sorted(m for m in sys.modules if m.startswith('dnd5e_engine')))"
)


def _loaded_modules() -> list[str]:
    out = subprocess.run(
        [sys.executable, "-W", "error::DeprecationWarning:dnd5e_engine", "-c", GEN2_ENTRY],
        check=True,
        capture_output=True,
        text=True,
    )
    loaded = ast.literal_eval(out.stdout)
    assert isinstance(loaded, list)
    return loaded


def test_gen2_entry_points_load_no_gen1_module() -> None:
    loaded = _loaded_modules()
    leaked = [m for m in loaded if m in GEN1]
    assert leaked == [], leaked
