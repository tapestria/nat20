"""Shared harness for the e2e scenario catalog tests.

Derived from the approved scenario catalog (local specs/e2e-scenario-catalog.md);
expectations cite SRD 5.2 and the Foundry VTT dnd5e reference. House style:
seeded start_combat + scripted intents + event-log assertions
(cf. tests/test_rage_second_wind_e2e.py).
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from dnd5e_engine.specs import SceneTopology, ZoneEdge


def run_async(coro: Any) -> Any:
    return asyncio.run(coro)


def single_zone() -> SceneTopology:
    return SceneTopology(
        zones=["zone:start"],
        edges=[ZoneEdge(a="zone:start", b="zone:start", distance_ft=0)],
    )


def events_of(live: Any, kind: type) -> list[Any]:
    return [e for e in live.event_log if isinstance(e, kind)]


def xfail_cluster(number: int, name: str) -> pytest.MarkDecorator:
    """Strict xfail tied to a backlog cluster; removed in the PR that closes it."""
    return pytest.mark.xfail(
        strict=True,
        reason=f"backlog cluster {number} ({name}) not yet implemented",
    )
