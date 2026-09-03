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
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

if TYPE_CHECKING:
    from dnd5e_srd_data.schema.spell import Spell

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


def count_scales_with_cast_level(count_formula: str) -> bool:
    """True when a Foundry ``target.affects.count`` formula genuinely encodes the
    R5 upcast mechanic — i.e. it references ``@item.level`` (the cast's slot
    level). A blank formula, or a FIXED marker like ``"1"`` (the schema default
    that a plain single-target damage/save/utility activity carries — Hex,
    Hunter's Mark, Revivify, Wall of Fire's per-creature save, ...), is NOT an
    upcast mechanic: it must not engage the R5 count-expansion machinery (target
    fan-out, damage dice-scaling suppression) at all. The single source of truth
    both ``orchestrator._find_count_activity`` and ``activities/damage.py``'s
    dice-scaling guard consult.
    """
    return bool(count_formula.strip()) and _ITEM_LEVEL_TOKEN in count_formula


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


_COMPONENT_ORDER: Final[tuple[Literal["V", "S", "M"], ...]] = ("V", "S", "M")


def spell_component_metadata(
    spell: Spell,
) -> tuple[tuple[Literal["V", "S", "M"], ...], str | None, bool, int]:
    """Project a ``Spell`` doc's component/material fields into the
    ``(components, material, material_consumed, material_cost_gp)`` tuple
    shared by ``SpellCast`` (orchestrator emission) and ``resolve_ritual_cast``
    below. SRD 5.2 §Components: "A spell's components are physical
    requirements the spellcaster must meet to cast the spell." Metadata
    only — never enforced (host decision, spec §5 C17)."""
    comps = tuple(c for c in _COMPONENT_ORDER if c in {str(x) for x in spell.components})
    return (
        comps,
        (spell.materials.value or None),
        bool(spell.materials.consumed),
        int(spell.materials.cost),
    )


@dataclass(frozen=True)
class RitualCast:
    """Out-of-combat resolution of a Ritual-tagged spell (C17 R8). SRD 5.2
    §Rituals: "The Ritual version of a spell takes 10 minutes longer to cast
    than normal, but it doesn't expend a spell slot. To cast a spell as a
    Ritual, a spellcaster must have it prepared."
    """

    spell_id: str
    casting_time_minutes: int
    slot_consumed: bool  # always False
    components: tuple[Literal["V", "S", "M"], ...]
    material: str | None
    material_consumed: bool
    material_cost_gp: int


def resolve_ritual_cast(spell: Spell, *, prepared: bool, ritual_adept: bool = False) -> RitualCast:
    """Resolve a Ritual-tagged spell cast outside the turn economy (R8).

    SRD 5.2 §Rituals: "To cast a spell as a Ritual, a spellcaster must have
    it prepared." §Ritual Adept (feat): "You needn't have the spell
    prepared." Raises ``ValueError`` when ``spell`` carries no Ritual tag, or
    when neither ``prepared`` nor ``ritual_adept`` is set. The 10-minute
    Ritual tax is additive on top of the spell's own casting time (``minute``
    unit adds its ``value`` in minutes; ``hour`` adds ``value * 60``; any
    other unit — e.g. ``action`` — contributes 0 base minutes).
    """
    if not spell.ritual:
        raise ValueError(f"{spell.slug!r} has no Ritual tag")
    if not prepared and not ritual_adept:
        raise ValueError(
            "a ritual cast requires the spell to be prepared (Ritual Adept waives this)"
        )
    unit = spell.casting_time.unit
    value = spell.casting_time.value or 0
    if str(unit) == "minute":
        base_minutes = value
    elif str(unit) == "hour":
        base_minutes = value * 60
    else:
        base_minutes = 0
    comps, material, consumed, cost = spell_component_metadata(spell)
    return RitualCast(
        spell_id=spell.slug,
        casting_time_minutes=base_minutes + 10,
        slot_consumed=False,
        components=comps,
        material=material,
        material_consumed=consumed,
        material_cost_gp=cost,
    )


__all__ = [
    "PACT_SLOT_TABLE",
    "SPELL_SLOT_TABLE",
    "RitualCast",
    "SpellcastingProgression",
    "count_scales_with_cast_level",
    "derive_pact_slots",
    "derive_spell_slots",
    "effective_caster_level",
    "multiclass_caster_level",
    "resolve_ritual_cast",
    "resolve_target_count",
    "slots_for_caster_level",
    "spell_component_metadata",
]
