"""Coverage backfill — public combat-seam error classes.

``CombatHandle``, ``UnknownHandleError`` (and its base ``CombatSeamError``), and
the public read accessor ``get_live`` are in ``orchestrator.__all__``. Tapestria
integration tests assert the seam raises typed errors so WS dispatch can branch
on them, but no ported engine test exercised the unknown-handle path directly.
These hermetic tests cover the registry-miss verdict for the public read
accessor and both public turn-drivers. Zero I/O.
"""

from __future__ import annotations

import asyncio

import pytest

from dnd5e_engine import PlayerIntent
from dnd5e_engine.orchestrator import (
    CombatHandle,
    CombatSeamError,
    UnknownHandleError,
    advance_monster_turn,
    get_live,
    submit_player_intent,
)


def test_unknown_handle_is_a_combat_seam_error() -> None:
    # Subclass relationship is part of the public contract: WS dispatch catches
    # CombatSeamError broadly.
    assert issubclass(UnknownHandleError, CombatSeamError)


def test_get_live_unknown_handle_raises() -> None:
    with pytest.raises(UnknownHandleError):
        get_live(CombatHandle(handle_id="nonexistent"))


def test_advance_monster_turn_unknown_handle_raises() -> None:
    with pytest.raises(UnknownHandleError):
        asyncio.run(advance_monster_turn(CombatHandle(handle_id="nonexistent")))


def test_submit_player_intent_unknown_handle_raises() -> None:
    intent = PlayerIntent(intent_type="pass")
    with pytest.raises(UnknownHandleError):
        asyncio.run(
            submit_player_intent(
                CombatHandle(handle_id="nonexistent"),
                "char:aaaaaaaaaaaa",
                intent,
            )
        )
