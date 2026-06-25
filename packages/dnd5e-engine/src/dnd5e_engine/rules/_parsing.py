"""Library-internal value parser — stdlib only.

Mirrors backend/app/utils/parsing.py::safe_parse_json minus the structlog
fallback warning. Used by dnd5e_engine.rules.resolution to parse Neo4j
property values (JSON strings or Python-literal strings) passed in by
the host.

SECURITY: ast.literal_eval is restricted by CPython to literals only —
numbers, strings, tuples, lists, dicts, booleans, None. Never pass
user-supplied input directly; this helper assumes trusted server-side
data (graph node properties).
"""

from __future__ import annotations

import ast
import json
from typing import Any


def safe_parse_json(value: Any, fallback: Any = None) -> Any:
    if value is None:
        return fallback
    if not isinstance(value, str):
        return value
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        pass
    try:
        return ast.literal_eval(value)
    except (ValueError, SyntaxError):
        pass
    return fallback
