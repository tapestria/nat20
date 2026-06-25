"""Typed Foundry Activity resolver.

Parallel to the Avrae-IR ``effects/`` package: consumes the typed
``dnd5e_srd_data`` ``Activity`` discriminated union and emits the engine's
existing ``CombatEvent`` union via an ``event_emitter`` callback.
"""

from __future__ import annotations

from .context import ActivityResolutionContext
from .resolver import resolve_activity

__all__ = ["ActivityResolutionContext", "resolve_activity"]
