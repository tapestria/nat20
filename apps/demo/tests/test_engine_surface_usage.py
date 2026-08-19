import ast
from pathlib import Path

import dnd5e_engine

SRC = Path(__file__).parent.parent / "src" / "nat20_demo"


def test_demo_uses_only_public_engine_names() -> None:
    public = set(dnd5e_engine.__all__)
    violations: list[str] = []
    for py in SRC.rglob("*.py"):
        tree = ast.parse(py.read_text())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.startswith("dnd5e_engine")
            ):
                if node.module != "dnd5e_engine":
                    violations.append(f"{py.name}: submodule import {node.module}")
                else:
                    violations.extend(
                        f"{py.name}: {a.name}" for a in node.names if a.name not in public
                    )
            if isinstance(node, ast.Import):
                violations.extend(
                    f"{py.name}: bare import {a.name}"
                    for a in node.names
                    if a.name.startswith("dnd5e_engine")
                )
    assert violations == []
