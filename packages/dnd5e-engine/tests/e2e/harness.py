"""Shared harness for the end-to-end scenario tests.

Each scenario's expectations cite SRD 5.2 and the Foundry VTT dnd5e
reference. House style: seeded start_combat + scripted intents + event-log
assertions (cf. tests/test_rage_second_wind_e2e.py).
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from dnd5e_engine.spatial import cell_id
from dnd5e_engine.specs import GridScene


def run_async(coro: Any) -> Any:
    return asyncio.run(coro)


def grid_scene(width: int = 10, height: int = 10, **kw: Any) -> GridScene:
    """Default 10x10 grid scene for C12+ scenarios (grid-only per D8)."""
    return GridScene(width=width, height=height, **kw)


def cell(col: int, row: int) -> str:
    """Wraps ``dnd5e_engine.spatial.cell_id`` for e2e test setups."""
    return cell_id(col, row)


def events_of(live: Any, kind: type) -> list[Any]:
    return [e for e in live.event_log if isinstance(e, kind)]


def xfail_cluster(number: int, name: str) -> pytest.MarkDecorator:
    """Strict xfail tied to a backlog cluster; removed in the PR that closes it."""
    return pytest.mark.xfail(
        strict=True,
        reason=f"backlog cluster {number} ({name}) not yet implemented",
    )


def adjacent_cells(n: int, *, at: tuple[int, int] = (0, 0)) -> list[str]:
    """1-4 mutually adjacent cell ids: the 2x2 block at ``at``, ordered (c,r),
    (c,r+1), (c+1,r), (c+1,r+1). The grid stand-in for one shared zone: every
    pair is 5 ft apart and no creature stands between two others."""
    if not 1 <= n <= 4:
        raise ValueError(f"adjacent_cells takes 1-4 cells, got {n}")
    col, row = at
    return [cell(col, row), cell(col, row + 1), cell(col + 1, row), cell(col + 1, row + 1)][:n]
