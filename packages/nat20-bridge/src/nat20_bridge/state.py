from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dnd5e_engine import CombatEvent, CombatHandle, GridScene
    from dnd5e_srd_data.loader import AssetLoader

    from nat20_bridge.homebrew import HomebrewStore


@dataclass
class BridgeState:
    homebrew_path: Path
    # Monotonically increasing counter for combat_id allocation — never
    # reused, even after a combat ends and is popped from `combats`. Using
    # `len(combats) + 1` for the id (as an earlier draft did) collides once
    # any combat has been removed: start A (c1), start B (c2), end A, start
    # C -> len(combats) is back down to 1, so C would mint "c2" again and
    # silently clobber B's still-live combats/events_log/names/seeds/
    # collectors entries.
    next_combat_id: int = 1
    combats: dict[str, CombatHandle] = field(default_factory=dict)
    events_log: dict[str, list[CombatEvent]] = field(default_factory=dict)
    seeds: dict[str, int] = field(default_factory=dict)
    # entity_id -> display name, per combat_id. Used to render narration and
    # the GET /v1/combat/{cid} view without re-deriving names from the
    # engine's Combatant rows (which only carry the name the caller gave it
    # at start_combat time anyway).
    names: dict[str, dict[str, str]] = field(default_factory=dict)
    # The battlefield each combat was started on, per combat_id. The engine
    # takes the scene at start_combat time and does not hand it back through
    # LiveCombatView, so the bridge keeps its own copy to serve the grid
    # block on GET /v1/combat/{cid} (hosts need the extent and terrain to
    # render the zones the view already reports).
    grids: dict[str, GridScene] = field(default_factory=dict)
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
