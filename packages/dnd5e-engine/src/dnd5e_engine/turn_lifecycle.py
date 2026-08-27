"""Turn-boundary hook registry — the one place work happens at a turn edge.

SRD 5.2 scatters "at the start of your turn" / "at the end of your turn"
clauses across effects (ongoing damage, regeneration), monster features
(recharge, legendary-action reset) and timed durations. Before this module the
engine had no seam for them: the duration tick and the reaction-effect expiry
were open-coded inside the orchestrator's three separate turn-advance
implementations, so every new boundary rule meant another hand-placed call in
three places.

``TurnLifecycle`` is that seam. One instance lives on each ``_LiveCombat``
(``live.lifecycle``, created in ``start_combat``). Callers register a
``TurnHook`` against one of three phases and the orchestrator's single
turn-advance path runs them:

    round_start   once per round, on wrap (``actor_id`` is ``None``)
    turn_start    after ``TurnStarted`` for the incoming actor
    turn_end      before ``TurnEnded`` for the outgoing actor

**Determinism.** Hooks run in registration order within a phase — never a set
or dict-hash order — so a seeded replay reproduces the same event sequence.
Hooks must not draw from ``live.rng`` unless the rule they implement genuinely
rolls dice; if one does, its position in the registration order is part of the
seed contract.

**Purity.** This module deliberately knows nothing about the orchestrator: the
``_LiveCombat`` reference is a ``TYPE_CHECKING``-only import, so there is no
runtime import cycle and hooks that need orchestrator internals (``_emit``,
event classes) are *registered from* the orchestrator rather than defined here.

Each phase is also marked in the event stream by a ``TurnPhase`` event
(``dnd5e_engine.events``) so hosts can render turn boundaries without
reconstructing them from ``TurnStarted`` / ``TurnEnded`` adjacency.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from dnd5e_engine.events import TurnPhaseName

if TYPE_CHECKING:  # pragma: no cover - typing-only, avoids an import cycle
    from dnd5e_engine.orchestrator import _LiveCombat

__all__ = [
    "TurnHook",
    "TurnLifecycle",
    "TurnPhaseName",
    "run_round_start",
    "run_turn_end",
    "run_turn_start",
]


#: A turn-boundary callback: ``(live, actor_id)``. ``actor_id`` is the actor
#: whose turn is starting/ending, or ``None`` for ``round_start``.
TurnHook = Callable[["_LiveCombat", "str | None"], None]

_PHASES: tuple[TurnPhaseName, ...] = ("round_start", "turn_start", "turn_end")


class TurnLifecycle:
    """Per-combat registry of turn-boundary hooks, keyed by phase.

    Registration order is preserved and is the execution order. ``key`` is a
    stable identity for the hook so a later feature can replace or retire it
    (``unregister``) without holding the function object; keys are unique
    across the whole registry, not per-phase.
    """

    def __init__(self) -> None:
        self._hooks: dict[TurnPhaseName, list[tuple[str, TurnHook]]] = {
            phase: [] for phase in _PHASES
        }

    def register(self, phase: TurnPhaseName, hook: TurnHook, *, key: str) -> None:
        """Append ``hook`` to ``phase``'s run list under ``key``.

        Raises ``ValueError`` if ``key`` is already registered (in any phase) —
        silently shadowing a hook would make the run order depend on import
        order, which is exactly the non-determinism this registry exists to
        prevent. Call ``unregister`` first to replace one.
        """
        if phase not in self._hooks:
            raise ValueError(f"unknown turn phase: {phase!r}")
        for registered in self._hooks.values():
            if any(k == key for k, _ in registered):
                raise ValueError(f"turn hook key already registered: {key!r}")
        self._hooks[phase].append((key, hook))

    def unregister(self, key: str) -> None:
        """Remove the hook registered under ``key``. No-op if absent.

        Safe to call from inside a hook during ``run`` (self-retiring
        one-shot hooks) — ``run`` iterates a snapshot.
        """
        for phase, registered in self._hooks.items():
            self._hooks[phase] = [(k, h) for k, h in registered if k != key]

    def run(self, live: _LiveCombat, phase: TurnPhaseName, actor_id: str | None) -> None:
        """Invoke every hook registered for ``phase``, in registration order.

        Iterates a tuple snapshot so a hook may register or unregister hooks
        (including itself) mid-run without corrupting the iteration; those
        edits take effect from the next ``run``.
        """
        for _key, hook in tuple(self._hooks.get(phase, ())):
            hook(live, actor_id)


def run_round_start(live: _LiveCombat) -> None:
    """Run the ``round_start`` hooks for ``live`` (no actor)."""
    live.lifecycle.run(live, "round_start", None)


def run_turn_start(live: _LiveCombat, actor_id: str | None) -> None:
    """Run the ``turn_start`` hooks for the actor whose turn is beginning."""
    live.lifecycle.run(live, "turn_start", actor_id)


def run_turn_end(live: _LiveCombat, actor_id: str | None) -> None:
    """Run the ``turn_end`` hooks for the actor whose turn is ending."""
    live.lifecycle.run(live, "turn_end", actor_id)
