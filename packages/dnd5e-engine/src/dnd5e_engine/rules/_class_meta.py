"""SRD 5.1 caster-class slug set — host-agnostic.

The library covers the canonical SRD 5.1 caster classes: all six full
casters (bard, cleric, druid, sorcerer, warlock, wizard) plus the two
half casters with spell lists (paladin, ranger). Hosts that materialize
a narrower subset still work — they simply won't reach the library
code paths for unseeded classes.
"""

from __future__ import annotations

CASTER_CLASS_SLUGS: frozenset[str] = frozenset(
    {"bard", "cleric", "druid", "paladin", "ranger", "sorcerer", "warlock", "wizard"}
)
