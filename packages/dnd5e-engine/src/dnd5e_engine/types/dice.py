"""DiceOutcome — server→client resolved dice roll result.

**DEPRECATED (0.4.0) — removed in 0.5.0.** See docs/migration/v0.3-to-v0.4.md.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class DiceOutcome(BaseModel):
    """Server → Client: resolved dice roll result."""

    type: Literal["DiceOutcome"] = "DiceOutcome"
    request_id: str
    character_id: str
    roll_type: str
    target_id: str | None = None
    roll_total: int  # die + modifier
    natural_roll: int  # raw d20 value
    modifier: int
    dice: list[int]  # all dice rolled (2 for advantage)
    dc: int | None = None  # DC or AC checked against
    success: bool | None = None  # None if no DC
    is_critical: bool = False
    is_fumble: bool = False
    summary: str = ""  # e.g. "Persuasion check: 18 vs DC 15 — Success!"
    die_size: int = 20  # Die type: 20 for d20, 6 for d6, etc. Frontend formats as d{die_size}


__all__ = [
    "DiceOutcome",
]


# ── 0.4.0 deprecation (module-level, fires once on first import) ─────────────
import warnings as _warnings  # noqa: E402

_warnings.warn(
    "dnd5e_engine.types.dice is part of the legacy (Gen 1) surface and will be "
    "removed in dnd5e-engine 0.5.0 — see docs/migration/v0.3-to-v0.4.md.",
    DeprecationWarning,
    stacklevel=2,
)
