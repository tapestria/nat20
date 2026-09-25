"""SRD 5.2 limited-use caps: the ``uses.max`` formulas the corpus states.

Foundry writes a feature's cap as roll data — ``@prof``, ``max(1,
@abilities.cha.mod)``, ``5 * @classes.paladin.levels``. This module evaluates
that grammar for one character without I/O: tokens become the character's
numbers, then ``ast`` walks the arithmetic (never ``eval``). A formula outside
the grammar is ``None``, which callers read as "uncapped", so a resource is
never wrongly refused.
"""

from __future__ import annotations

import ast
import operator
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Final, cast

from dnd5e_engine.events import Ability

_TOKEN_RE: Final = re.compile(r"@[A-Za-z][A-Za-z0-9_-]*(?:\.[A-Za-z0-9_-]+)*")
_ABILITY_MOD_RE: Final = re.compile(r"^@abilities\.(str|dex|con|int|wis|cha)\.mod$")
_CLASS_LEVELS_RE: Final = re.compile(r"^@classes\.([a-z0-9-]+)\.levels$")
_SCALE_PREFIX: Final = "@scale."
_BINARY: Final[dict[type[ast.operator], Callable[[int, int], int]]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
}
_FUNCTIONS: Final[dict[str, Callable[..., int]]] = {"max": max, "min": min}


@dataclass(frozen=True)
class UsesRollData:
    """The numbers a limited-use formula may read for one character."""

    proficiency_bonus: int | None = None
    ability_modifiers: Mapping[Ability, int] = field(default_factory=dict)
    class_levels: Mapping[str, int] = field(default_factory=dict)
    scale_values: Mapping[str, int | str] = field(default_factory=dict)


class _UnsupportedFormulaError(ValueError):
    """A token or construct outside the limited-use grammar."""


def evaluate_uses_formula(expr: str, roll_data: UsesRollData) -> int | None:
    """Evaluate ``expr``: integers, ``@prof``, ``@abilities.<ab>.mod``,
    ``@classes.<slug>.levels``, integer ``@scale.<key>`` values, ``+ - *``,
    unary minus, parentheses and ``max`` / ``min`` of two or more terms.
    ``None`` for anything else or a value the character doesn't have."""
    try:
        text = _TOKEN_RE.sub(lambda m: f"({_token_value(m.group(0), roll_data)})", expr)
        return _evaluate(ast.parse(text.strip(), mode="eval").body)
    except (SyntaxError, ValueError):
        return None


def _token_value(ref: str, roll_data: UsesRollData) -> int:
    value: int | str | None = None
    if ref == "@prof":
        value = roll_data.proficiency_bonus
    elif match := _ABILITY_MOD_RE.match(ref):
        value = roll_data.ability_modifiers.get(cast("Ability", match.group(1)))
    elif match := _CLASS_LEVELS_RE.match(ref):
        value = roll_data.class_levels.get(match.group(1))
    elif ref.startswith(_SCALE_PREFIX):
        value = roll_data.scale_values.get(ref.removeprefix(_SCALE_PREFIX))
    if not isinstance(value, int):
        raise _UnsupportedFormulaError(ref)
    return value


def _evaluate(node: ast.expr) -> int:
    if isinstance(node, ast.Constant) and type(node.value) is int:
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_evaluate(node.operand)
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
        return _BINARY[type(node.op)](_evaluate(node.left), _evaluate(node.right))
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in _FUNCTIONS
        and len(node.args) >= 2
        and not node.keywords
    ):
        return _FUNCTIONS[node.func.id](*(_evaluate(arg) for arg in node.args))
    raise _UnsupportedFormulaError(ast.dump(node))


__all__ = ["UsesRollData", "evaluate_uses_formula"]
