"""Test-support seam for host suites driving and inspecting live combat.

The orchestrator keeps its live-combat registry and event-emission helpers
private (underscore-prefixed) because they are not part of the combat seam's
narrative contract. Host test suites legitimately need a few of these internals
to drive and inspect live combat without re-implementing the registry. This
module is the single sanctioned access point for them, so test code never
reaches into the engine's private attributes across the package boundary.

Names here are test-support only and must not be used by production. The
read-only live-combat accessor that production host code may use is public on
``dnd5e_engine.orchestrator`` (``get_live``), not here.
"""

from __future__ import annotations

from dnd5e_engine.orchestrator import (
    _REGISTRY,
    _build_hydration_payload,
    _emit,
    _reset_registry_for_tests,
    _ZoneGraph,
)

__all__ = [
    "ZoneGraph",
    "build_hydration_payload",
    "emit",
    "registry",
    "reset_registry",
]

# Test-support: live-combat registry handle and lifecycle reset.
registry = _REGISTRY
reset_registry = _reset_registry_for_tests

# Test-support: event-emission and sidecar-hydration helpers used by boundary
# and scenario tests to drive the same code paths the per-effect handlers take.
emit = _emit
build_hydration_payload = _build_hydration_payload

# Test-support: zone-distance graph for within-range unit tests.
ZoneGraph = _ZoneGraph
