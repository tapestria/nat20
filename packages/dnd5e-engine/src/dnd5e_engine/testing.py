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

import random
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from dnd5e_engine import orchestrator
from dnd5e_engine.orchestrator import (
    _REGISTRY,
    _build_hydration_payload,
    _emit,
    _reset_registry_for_tests,
)

__all__ = [
    "build_hydration_payload",
    "emit",
    "registry",
    "reset_registry",
    "rng_factory",
]

# Test-support: live-combat registry handle and lifecycle reset.
registry = _REGISTRY
reset_registry = _reset_registry_for_tests

# Test-support: event-emission and sidecar-hydration helpers used by boundary
# and end-to-end tests to drive the same code paths the per-effect handlers take.
emit = _emit
build_hydration_payload = _build_hydration_payload


@contextmanager
def rng_factory(factory: Callable[[int], random.Random]) -> Iterator[None]:
    """Within the block, every combat ``start_combat`` opens draws its dice
    from ``factory(rng_seed)`` instead of ``random.Random(rng_seed)``.

    The factory returns a ``random.Random``; a subclass may override
    ``randint`` (the only method the engine draws with) to script or record
    rolls, Initiative rolled inside ``start_combat`` included. A combat keeps
    the RNG it opened with after the block ends. The override is process-wide
    for the duration of the block, not scoped to a task or thread. The default
    is restored on exit, also when the block raises. Test-support only.
    """
    previous = orchestrator._rng_factory
    orchestrator._rng_factory = factory
    try:
        yield
    finally:
        orchestrator._rng_factory = previous
