"""Pure CombatEvent → dict serialization.

Used by the host's WS-envelope adapter at app.combat.ws_projection.
Library-internal only — no WS protocol concerns leak in here. The host
owns Tapestria-specific envelope wrapping (SystemMessage, CombatEnd,
DeathSaveUpdate); the library only knows how to project an event to its
generic wire-shape dict.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from dnd5e_engine.events import CombatEvent


def event_to_dict(event: CombatEvent) -> dict[str, Any]:
    """Project a single CombatEvent to its generic wire-shape dict.

    This is the ``SessionEvent``-style envelope: a flat dict with the
    event's ``type`` discriminator and its full ``model_dump()`` as the
    payload. Host-side adapters may wrap this further in transport
    envelopes; the library has no opinion on transport.
    """
    return {
        "type": "SessionEvent",
        "event_type": event.type,
        "payload": event.model_dump(),
    }


def events_to_dicts(events: Iterable[CombatEvent]) -> list[dict[str, Any]]:
    return [event_to_dict(ev) for ev in events]


__all__ = ["event_to_dict", "events_to_dicts"]
