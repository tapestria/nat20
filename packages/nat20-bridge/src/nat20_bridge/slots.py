"""SRD 5.2 spell-slot progression tables.

The dnd5e-srd-data canonical class documents (``wizard.json``, ``paladin.json``,
``warlock.json``) do **not** carry spell-slot-per-level tables: their
``description`` prose only points readers at the (externally embedded) PHB
class-feature journal, and their ``advancement`` arrays only encode
``ScaleValue`` entries for things like "Cantrips Known" / "max prepared
spells" — never slot counts. So these tables are transcribed directly from
the SRD 5.2 rules text (Wizard spell slot table for ``full``, Paladin spell
slot table for ``half``, Warlock Pact Magic table for ``pact``), not from the
dataset. See project memory: never trust model memory for 5e rules without
double-checking against a primary text — these values were cross-checked
against the well-known, non-controversial SRD 5.2 tables at write time.

``Class.spellcasting.progression`` (``dnd5e_srd_data.schema.class_.
SpellcastingProgression``) is the closed set ``none | third | half | full |
pact | artificer``. This module only tabulates ``full``, ``half``, and
``pact`` — no SRD 5.2 base class uses ``third`` (that's a 2014-SRD Arcane
Trickster/Eldritch Knight subclass mechanic, not a base-class progression),
and ``artificer`` isn't an SRD 5.2 class. Both — and any other unrecognized
string — fall through to ``{}`` via ``slots_for``'s default lookup.
"""

from __future__ import annotations

# Wizard spell slot table (SRD 5.2), the reference "full caster" progression.
# Index 0 == level 1, ..., index 19 == level 20.
_FULL_CASTER_SLOTS: list[dict[int, int]] = [
    {1: 2},  # 1
    {1: 3},  # 2
    {1: 4, 2: 2},  # 3
    {1: 4, 2: 3},  # 4
    {1: 4, 2: 3, 3: 2},  # 5
    {1: 4, 2: 3, 3: 3},  # 6
    {1: 4, 2: 3, 3: 3, 4: 1},  # 7
    {1: 4, 2: 3, 3: 3, 4: 2},  # 8
    {1: 4, 2: 3, 3: 3, 4: 3, 5: 1},  # 9
    {1: 4, 2: 3, 3: 3, 4: 3, 5: 2},  # 10
    {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1},  # 11
    {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1},  # 12
    {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1, 7: 1},  # 13
    {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1, 7: 1},  # 14
    {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1, 7: 1, 8: 1},  # 15
    {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1, 7: 1, 8: 1},  # 16
    {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1, 7: 1, 8: 1, 9: 1},  # 17
    {1: 4, 2: 3, 3: 3, 4: 3, 5: 3, 6: 1, 7: 1, 8: 1, 9: 1},  # 18
    {1: 4, 2: 3, 3: 3, 4: 3, 5: 3, 6: 2, 7: 1, 8: 1, 9: 1},  # 19
    {1: 4, 2: 3, 3: 3, 4: 3, 5: 3, 6: 2, 7: 2, 8: 1, 9: 1},  # 20
]

# Paladin spell slot table (SRD 5.2), the reference "half caster" progression.
# Half casters get no slots at level 1.
_HALF_CASTER_SLOTS: list[dict[int, int]] = [
    {},  # 1
    {1: 2},  # 2
    {1: 3},  # 3
    {1: 3},  # 4
    {1: 4, 2: 2},  # 5
    {1: 4, 2: 2},  # 6
    {1: 4, 2: 3},  # 7
    {1: 4, 2: 3},  # 8
    {1: 4, 2: 3, 3: 2},  # 9
    {1: 4, 2: 3, 3: 2},  # 10
    {1: 4, 2: 3, 3: 3},  # 11
    {1: 4, 2: 3, 3: 3},  # 12
    {1: 4, 2: 3, 3: 3, 4: 1},  # 13
    {1: 4, 2: 3, 3: 3, 4: 1},  # 14
    {1: 4, 2: 3, 3: 3, 4: 2},  # 15
    {1: 4, 2: 3, 3: 3, 4: 2},  # 16
    {1: 4, 2: 3, 3: 3, 4: 3, 5: 1},  # 17
    {1: 4, 2: 3, 3: 3, 4: 3, 5: 1},  # 18
    {1: 4, 2: 3, 3: 3, 4: 3, 5: 2},  # 19
    {1: 4, 2: 3, 3: 3, 4: 3, 5: 2},  # 20
]

# Warlock Pact Magic table (SRD 5.2). Unlike the other two tables, every
# slot is the same (highest) level: only that entry is present.
_PACT_CASTER_SLOTS: list[dict[int, int]] = [
    {1: 1},  # 1
    {1: 2},  # 2
    {2: 2},  # 3
    {2: 2},  # 4
    {3: 2},  # 5
    {3: 2},  # 6
    {4: 2},  # 7
    {4: 2},  # 8
    {5: 2},  # 9
    {5: 2},  # 10
    {5: 3},  # 11
    {5: 3},  # 12
    {5: 3},  # 13
    {5: 3},  # 14
    {5: 3},  # 15
    {5: 3},  # 16
    {5: 4},  # 17
    {5: 4},  # 18
    {5: 4},  # 19
    {5: 4},  # 20
]

_TABLES: dict[str, list[dict[int, int]]] = {
    "full": _FULL_CASTER_SLOTS,
    "half": _HALF_CASTER_SLOTS,
    "pact": _PACT_CASTER_SLOTS,
    # "third" progression has no SRD 5.2 base class (the 2014 SRD's
    # Eldritch Knight / Arcane Trickster "third caster" is a subclass
    # mechanic, not surfaced by dnd5e-srd-data as a base-class
    # progression) — leave empty for v1.
}


def slots_for(progression: str, level: int) -> dict[int, int]:
    """Return the ``{slot_level: count}`` spell slots for a class
    ``progression`` at character ``level``.

    Unknown/unsupported progressions (including ``"none"``, ``"third"``,
    ``"artificer"``, and anything not recognized) return ``{}``. ``level``
    is clamped to the SRD's 1-20 range.
    """
    table = _TABLES.get(progression)
    if table is None:
        return {}
    if level < 1:
        return {}
    index = min(level, 20) - 1
    return dict(table[index])
