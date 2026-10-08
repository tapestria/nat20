from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from dnd5e_engine import CombatHandle, GridScene
    from dnd5e_srd_data.loader import AssetLoader

    from nat20_bridge.homebrew import HomebrewStore

#: How many combats stay live at once unless ``--max-combats`` says otherwise.
DEFAULT_MAX_COMBATS: Final = 16


@dataclass
class CombatSession:
    """One live combat: the engine's handle and what the bridge serves beside it."""

    handle: CombatHandle
    # entity_id -> display name, for narration and the GET /v1/combat/{cid}
    # view. A creature that joins mid-combat (a summon) is added when its
    # ``combatant_joined`` event is drained.
    names: dict[str, str]
    # The battlefield the combat was started on. The engine takes the scene at
    # start_combat time and does not hand it back through LiveCombatView, so
    # the bridge keeps it to serve the view's grid block.
    grid: GridScene
    seed: int


@dataclass
class BridgeState:
    homebrew_path: Path
    # Live combats are capped: starting one more ends the least recently used
    # (the engine releases a combat only once it has ended), and its id then
    # answers 404. max_combats must be ≥ 1. No clock and no background task
    # are involved.
    max_combats: int = DEFAULT_MAX_COMBATS
    # Monotonically increasing counter for combat_id allocation — never
    # reused, even after a combat ends and leaves `sessions`. Using
    # `len(sessions) + 1` for the id collides once any combat has been
    # removed: start A (c1), start B (c2), end A, start C -> len(sessions)
    # is back down to 1, so C would mint "c2" again and silently clobber
    # B's still-live session.
    next_combat_id: int = 1
    # Live combats by combat_id, least recently used first: every request
    # that names a combat moves it to the end. Only the async combat routes
    # touch it, all on the event loop's thread, and none yields mid-update,
    # so it takes no lock: a sync route (FastAPI runs those on its thread
    # pool) must not touch it.
    sessions: OrderedDict[str, CombatSession] = field(default_factory=OrderedDict)
    # The homebrew store + the overlay loader built from it, and a callable
    # to rebuild the overlay after a homebrew mutation (Task 10). Populated
    # by ``create_app`` — never ``None`` once the app is constructed.
    homebrew_store: HomebrewStore | None = None
    loader: AssetLoader | None = None
    refresh_loader: Callable[[], None] | None = None
