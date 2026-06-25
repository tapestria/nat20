"""Resolve a single skill check with the public dnd5e-engine API.

``resolve_check`` is a pure function: it reads only the ``CheckSpec`` you
hand it and rolls via the standard library ``random`` module, so seeding
``random`` up front makes the result deterministic.
"""

from __future__ import annotations

import random

from dnd5e_engine import CheckSpec, resolve_check

# Fixed seed => reproducible roll every run.
random.seed(42)

# A proficient Rogue (Dex 16, +2 proficiency) attempts a DC 15 Stealth check.
spec = CheckSpec(
    kind="skill",
    skill="stealth",
    ability_scores={"strength": 10, "dexterity": 16, "constitution": 12,
                    "intelligence": 10, "wisdom": 12, "charisma": 14},
    proficient_skills=("stealth",),
    proficient_saves=(),
    proficiency_bonus=2,
    dc=15,
)

result = resolve_check(spec)
verdict = "SUCCESS" if result.success else "FAILURE"
print(f"Stealth (d20={result.natural_roll}) total {result.roll_total} "
      f"vs DC {result.dc}: {verdict}")
