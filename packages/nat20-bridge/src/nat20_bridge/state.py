from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dnd5e_engine import CombatEvent, CombatHandle


@dataclass
class BridgeState:
    homebrew_path: Path
    combats: dict[str, CombatHandle] = field(default_factory=dict)
    events_log: dict[str, list[CombatEvent]] = field(default_factory=dict)
    seeds: dict[str, int] = field(default_factory=dict)
