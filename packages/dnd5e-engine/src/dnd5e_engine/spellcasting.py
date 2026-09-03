"""Pure SRD 5.2 spellcasting tables and derivations (C17).

Zero I/O, zero host imports. Loader access (class slug -> ``spellcasting.progression``)
stays with ``build_spec.derive_multiclass_slots``; this module reads only the
value-typed inputs it is handed.

SRD 5.2 ground truth (``content24/``):

* §Spell Slots — *"For example, a level 3 Wizard has four level 1 spell slots and
  two level 2 slots."* The per-level table is the Multiclass Spellcaster table
  (``chapter-2/character-creation.yml:784``), numerically identical to Foundry's
  ``SPELL_SLOT_TABLE`` (``module/config.mjs:3027``).
* §Multiclassing — *"All your levels in the Bard, Cleric, Druid, Sorcerer, and
  Wizard classes; Half your levels (round up) in the Paladin and Ranger classes."*
  Foundry parity: ``half`` = divisor 2 round UP, ``third`` = divisor 3 round DOWN,
  rounding applied PER CLASS before summing (``computeProgression``). A single
  half-caster therefore has slots at level 1 (``ceil(1/2) == 1``) — the 2014
  table's empty level-1 row is NOT what this repo pins.
* Pact Magic — *"You regain all expended Pact Magic spell slots when you finish a
  Short or Long Rest. … when you're a level 5 Warlock, you have two level 3 spell
  slots."* Foundry ``pactCastingProgression`` (``config.mjs:3053``); Pact levels
  never enter the multiclass total.
"""

from __future__ import annotations

import ast
import math
from collections.abc import Mapping
from typing import Final, Literal

SpellcastingProgression = Literal["full", "half", "third", "pact", "none", "artificer"]

#: Foundry ``SPELL_SLOT_TABLE`` — row i = caster level i+1, entries = slot
#: counts for spell levels 1..len.
SPELL_SLOT_TABLE: Final[tuple[tuple[int, ...], ...]] = (
    (2,),
    (3,),
    (4, 2),
    (4, 3),
    (4, 3, 2),
    (4, 3, 3),
    (4, 3, 3, 1),
    (4, 3, 3, 2),
    (4, 3, 3, 3, 1),
    (4, 3, 3, 3, 2),
    (4, 3, 3, 3, 2, 1),
    (4, 3, 3, 3, 2, 1),
    (4, 3, 3, 3, 2, 1, 1),
    (4, 3, 3, 3, 2, 1, 1),
    (4, 3, 3, 3, 2, 1, 1, 1),
    (4, 3, 3, 3, 2, 1, 1, 1),
    (4, 3, 3, 3, 2, 1, 1, 1, 1),
    (4, 3, 3, 3, 3, 1, 1, 1, 1),
    (4, 3, 3, 3, 3, 2, 1, 1, 1),
    (4, 3, 3, 3, 3, 2, 2, 1, 1),
)

#: Foundry ``pactCastingProgression`` densified — row i = warlock level i+1 -> (slot_level, count).
PACT_SLOT_TABLE: Final[tuple[tuple[int, int], ...]] = (
    (1, 1),
    (1, 2),
    (2, 2),
    (2, 2),
    (3, 2),
    (3, 2),
    (4, 2),
    (4, 2),
    (5, 2),
    (5, 2),
    (5, 3),
    (5, 3),
    (5, 3),
    (5, 3),
    (5, 3),
    (5, 3),
    (5, 4),
    (5, 4),
    (5, 4),
    (5, 4),
)

_DIVISOR: Final[dict[str, tuple[int, bool]]] = {
    # progression -> (divisor, round_up)
    "full": (1, False),
    "half": (2, True),
    "third": (3, False),
    "artificer": (2, True),
}


def _check_level(level: int) -> None:
    if not 1 <= level <= 20:
        raise ValueError(f"level must be within 1..20, got {level}")


def effective_caster_level(progression: SpellcastingProgression, level: int) -> int:
    """Levels a single class contributes to the Spellcasting-feature total.

    ``full`` 1:1; ``half`` ``ceil(level / 2)``; ``third`` ``floor(level / 3)``;
    ``pact`` / ``none`` contribute 0 (Pact Magic is its own pool).
    """
    _check_level(level)
    rule = _DIVISOR.get(progression)
    if rule is None:
        return 0
    divisor, round_up = rule
    return math.ceil(level / divisor) if round_up else level // divisor


def slots_for_caster_level(caster_level: int) -> dict[int, int]:
    """Multiclass Spellcaster table row for a (possibly multiclass) caster level; ``{}`` at 0."""
    if caster_level <= 0:
        return {}
    if caster_level > 20:
        raise ValueError(f"caster level must be within 0..20, got {caster_level}")
    row = SPELL_SLOT_TABLE[caster_level - 1]
    return {slot_level: count for slot_level, count in enumerate(row, start=1)}


def derive_spell_slots(
    class_slug: str, progression: SpellcastingProgression, level: int
) -> dict[int, int]:
    """Single-class Spellcasting-feature slots ``{slot_level: count}``.

    ``class_slug`` is carried for error messages / provenance only — the table
    is keyed by ``progression``, which the caller reads off
    ``Class.spellcasting.progression``. ``pact``/``none`` yield ``{}``.
    """
    _check_level(level)
    if progression in ("pact", "none"):
        return {}
    return slots_for_caster_level(effective_caster_level(progression, level))


def derive_pact_slots(level: int) -> dict[int, int]:
    """Pact Magic pool for a Warlock ``level`` — all slots share ONE level."""
    _check_level(level)
    slot_level, count = PACT_SLOT_TABLE[level - 1]
    return {slot_level: count}


def multiclass_caster_level(
    classes: Mapping[str, tuple[SpellcastingProgression, int]],
) -> int:
    """SRD §Multiclassing Spell Slots — per-class rounded contributions, summed (R2)."""
    return sum(effective_caster_level(prog, lvl) for prog, lvl in classes.values())


_ITEM_LEVEL_TOKEN: Final = "@item.level"


def resolve_target_count(count_formula: str, *, cast_level: int) -> int | None:
    """Foundry ``target.affects.count`` roll-data → int, with ``@item.level`` = the
    cast's slot level (R5) — SRD 5.2 Magic Missile: "You create three glowing darts
    of magical force. … The spell creates one more dart for each spell slot level
    above 1." (``target.affects.count == "2 + @item.level"``). Supports integer
    literals, ``+ - *`` and parentheses; any other ``@`` token or AST node raises
    ``ValueError`` (loud — never a silent ``eval``/``exec``, which bandit forbids
    here anyway). Blank/whitespace-only ⇒ ``None`` (no count semantics). Floors
    at 1 (a spell never targets fewer than one creature via this path).
    """
    if not count_formula.strip():
        return None
    expr = count_formula.replace(_ITEM_LEVEL_TOKEN, str(cast_level))
    if "@" in expr:
        raise ValueError(f"unsupported roll-data token in target count: {count_formula!r}")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"unparseable target count: {count_formula!r}") from exc
    return max(1, _eval_int(tree.body))


def _eval_int(node: ast.AST) -> int:
    """Restricted AST evaluator for ``resolve_target_count`` — literal ints, unary
    +/-, and binary +/-/* only. No name lookups, no calls, no attribute access:
    this is deliberately not ``eval``/``exec`` (bandit-forbidden in this repo)."""
    if (
        isinstance(node, ast.Constant)
        and isinstance(node.value, int)
        and not isinstance(node.value, bool)
    ):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        v = _eval_int(node.operand)
        return v if isinstance(node.op, ast.UAdd) else -v
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult)):
        a, b = _eval_int(node.left), _eval_int(node.right)
        if isinstance(node.op, ast.Add):
            return a + b
        if isinstance(node.op, ast.Sub):
            return a - b
        return a * b
    raise ValueError(f"unsupported expression node in target count: {type(node).__name__}")


__all__ = [
    "PACT_SLOT_TABLE",
    "SPELL_SLOT_TABLE",
    "SpellcastingProgression",
    "derive_pact_slots",
    "derive_spell_slots",
    "effective_caster_level",
    "multiclass_caster_level",
    "resolve_target_count",
    "slots_for_caster_level",
]
