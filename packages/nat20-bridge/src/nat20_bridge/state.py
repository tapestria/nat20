from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dnd5e_engine import CombatEvent, CombatHandle
    from dnd5e_srd_data.loader import AssetLoader

    from nat20_bridge.homebrew import HomebrewStore


@dataclass
class BridgeState:
    homebrew_path: Path
    combats: dict[str, CombatHandle] = field(default_factory=dict)
    events_log: dict[str, list[CombatEvent]] = field(default_factory=dict)
    seeds: dict[str, int] = field(default_factory=dict)
    # entity_id -> display name, per combat_id. Used to render narration and
    # the GET /v1/combat/{cid} view without re-deriving names from the
    # engine's Combatant rows (which only carry the name the caller gave it
    # at start_combat time anyway).
    names: dict[str, dict[str, str]] = field(default_factory=dict)
    # Background collector tasks draining ``narration_events(handle)`` into
    # ``events_log[cid]`` for the lifetime of each combat — see
    # ``routes_combat.py``'s module docstring for the drain protocol. Kept
    # here (not just fire-and-forgot) so the task object stays referenced
    # (asyncio only guarantees a task survives GC while something holds it)
    # and so ``end_combat`` can await its clean shutdown.
    collectors: dict[str, asyncio.Task[None]] = field(default_factory=dict)
    # The homebrew store + the overlay loader built from it, and a callable
    # to rebuild the overlay after a homebrew mutation (Task 10). Populated
    # by ``create_app`` — never ``None`` once the app is constructed.
    homebrew_store: HomebrewStore | None = None
    loader: AssetLoader | None = None
    refresh_loader: Callable[[], None] | None = None
