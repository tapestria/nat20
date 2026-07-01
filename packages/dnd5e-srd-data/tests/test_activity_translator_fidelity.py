"""Activity translator fidelity gate (Phase 7b PR A — task A4).

Walks ``tests/oracle/activity_oracle.json`` — the answer key built from a
one-time traversal of every Foundry source YAML — and asserts that
``tools.translators.foundry._translate_activities`` round-trips every
structured field present in the Foundry activity subtree into the per-kind
A3 Pydantic models.

The oracle stores Foundry's raw camelCase dict; the translator emits
snake_case Pydantic models. Comparison reverses the casing once on the
oracle side (the closed ``_ACTIVITY_CAMEL_TO_SNAKE`` map matches the
translator's own table) and asserts every (oracle) key/value appears in
the (translator-output) dump with equal value.

A small number of Foundry-side fields are not (yet) representable in A3
and are skipped via ``KNOWN_ACTIVITY_FIDELITY_EXCEPTIONS`` — recorded for
A3 follow-up. The fidelity contract for everything else is **strict**:
every other key in the oracle subtree must be preserved.

Failure mode: aggregate diagnostics, cap at 200 lines, emit one
xfail-style block per failing activity. Pattern mirrors the existing
``test_translator_fidelity.py``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from tools.translators.foundry import _build_activity, _normalize_activity_dict

ROOT = Path(__file__).resolve().parent.parent
ORACLE_PATH = ROOT / "tests" / "oracle" / "activity_oracle.json"

# Foundry-side fields the A3 schema cannot represent losslessly, scoped by
# activity kind (``"*"`` = every kind). Track each as an A3 follow-up; do NOT
# widen these sets to mask real translator bugs. Values are top-level oracle
# ``system`` keys.
#
#   appliedEffects  — legacy flat list[str] of effect ids that mostly
#                     duplicates the structured ``effects[]._id`` slice.
#                     Present in 282 oracle entries (274 empty + 8 with
#                     content); the 4 non-empty cases (hunters-mark,
#                     ring-of-invisibility, shillelagh, wand-of-paralysis)
#                     are tracked for the A3 follow-up that introduces an
#                     ``applied_effects`` field on the per-kind models.
#   roll (save only) — Foundry's ``save-data.mjs`` schema has no ``roll``
#                     field (it lives only on utility/transform); a single
#                     2024 source doc (cleric channel-divinity / Turn Undead)
#                     carries a stray empty default ``roll`` block that
#                     Foundry itself discards on load. Excepted on ``save``
#                     only so a real ``roll`` mismatch on utility/transform
#                     still fails.
KNOWN_ACTIVITY_FIDELITY_EXCEPTIONS: dict[str, set[str]] = {
    "*": {"appliedEffects"},
    "save": {"roll"},
}


# Documented translator coercions where oracle and translator-dumped values
# legitimately differ in shape. Each predicate returns True iff the
# (oracle, actual) pair matches the documented coercion at the given path.
# Adding a new translator coercion = adding a new entry here (single source
# of truth, paired with the translator-side coercion helper).
Tolerance = Callable[[Any, Any, list[str]], bool]


def _tol_scalar_to_singleton_list(o: Any, a: Any, _p: list[str]) -> bool:
    """Foundry's set-typed save.ability YAML-serializes as scalar OR list;
    translator promotes a non-empty scalar → single-element list, and a falsy
    scalar (``''``, "no save ability") → empty list (see
    foundry._coerce_save_ability)."""
    if isinstance(o, str) and isinstance(a, list):
        return a == [o] if o else a == []
    return False


def _tol_empty_list_to_default_riders(o: Any, a: Any, _p: list[str]) -> bool:
    """Foundry's enchant.effects[*].riders ``[]`` placeholder coerced to the
    EnchantEffectRiders default dump (empty dict via exclude_unset, OR a dict
    where every value is an empty list)."""
    return o == [] and isinstance(a, dict) and all(v == [] for v in a.values())


def _tol_numeric_str_to_int(o: Any, a: Any, _p: list[str]) -> bool:
    """Foundry stores numeric fields (spell.level, damage.parts[].number /
    .denomination, healing.denomination) as YAML strings; Pydantic's
    NonNegativeInt coerces ``"4"`` → ``4``."""
    if isinstance(o, str) and isinstance(a, int) and not isinstance(a, bool):
        try:
            return int(o) == a
        except ValueError:
            return False
    return False


def _tol_null_to_empty_str(o: Any, a: Any, p: list[str]) -> bool:
    """Translator coerces ``img: null`` / ``name: null`` → empty string so
    Pydantic's ``str`` typing validates (see foundry._build_activity)."""
    return o is None and a == "" and bool(p) and p[-1] in {"img", "name"}


_TOLERANCES: tuple[Tolerance, ...] = (
    _tol_scalar_to_singleton_list,
    _tol_empty_list_to_default_riders,
    _tol_numeric_str_to_int,
    _tol_null_to_empty_str,
)


def _is_excepted(_path: list[str], field: str, activity_kind: str) -> bool:
    return field in KNOWN_ACTIVITY_FIDELITY_EXCEPTIONS.get(
        "*", set()
    ) or field in KNOWN_ACTIVITY_FIDELITY_EXCEPTIONS.get(activity_kind, set())


def _compare_subset(
    oracle: Any,
    actual: Any,
    path: list[str],
    failures: list[str],
    activity_kind: str,
) -> None:
    """Assert every oracle key/value is present in ``actual`` with equal value.
    Recurses into nested dicts / lists. Documented translator coercions are
    declared as ``_TOLERANCES`` and consulted before any type-specific
    mismatch is recorded. Drops keys listed in
    ``KNOWN_ACTIVITY_FIDELITY_EXCEPTIONS``."""
    # Single consultation of the tolerance table — covers list-shape AND
    # scalar-shape coercions without duplicating per-branch.
    if any(tol(oracle, actual, path) for tol in _TOLERANCES):
        return
    if isinstance(oracle, dict):
        if not isinstance(actual, dict):
            failures.append(
                f"{'.'.join(path) or '<root>'}: oracle is dict but actual is "
                f"{type(actual).__name__} ({actual!r:.80})"
            )
            return
        for k, v in oracle.items():
            if _is_excepted(path, k, activity_kind):
                continue
            sub_path = [*path, k]
            if k not in actual:
                failures.append(
                    f"{'.'.join(sub_path)}: missing in translator output (oracle value={v!r:.80})"
                )
                continue
            _compare_subset(v, actual[k], sub_path, failures, activity_kind)
        return
    if isinstance(oracle, list):
        if not isinstance(actual, list):
            failures.append(
                f"{'.'.join(path) or '<root>'}: oracle is list but actual is "
                f"{type(actual).__name__}"
            )
            return
        if len(oracle) != len(actual):
            failures.append(
                f"{'.'.join(path)}: list length mismatch oracle={len(oracle)} actual={len(actual)}"
            )
            return
        for i, (ov, av) in enumerate(zip(oracle, actual, strict=True)):
            _compare_subset(ov, av, [*path, str(i)], failures, activity_kind)
        return
    # Scalar mismatch (tolerances already consulted at the top).
    if oracle != actual:
        failures.append(
            f"{'.'.join(path)}: value mismatch oracle={oracle!r:.80} actual={actual!r:.80}"
        )


@pytest.fixture(scope="module")
def oracle() -> dict[str, dict[str, Any]]:
    return json.loads(ORACLE_PATH.read_text(encoding="utf-8"))


def test_every_oracle_activity_builds(oracle: dict[str, dict[str, Any]]) -> None:
    """Smoke: every oracle entry produces a non-None Pydantic activity."""
    failures: list[str] = []
    for key, entry in oracle.items():
        system = entry["system"]
        try:
            act = _build_activity(str(system.get("_id", "")), system)
        except Exception as e:  # aggregate-then-fail diagnostics
            failures.append(f"{key}: build raised {type(e).__name__}: {e}")
            continue
        if act is None:
            failures.append(
                f"{key}: build returned None (activity_kind={entry['activity_kind']!r})"
            )
    if failures:
        body = "\n".join(failures[:200])
        pytest.fail(f"{len(failures)} activity build failures (showing first 200):\n{body}")


def test_every_oracle_field_round_trips(oracle: dict[str, dict[str, Any]]) -> None:
    """Strict per-field fidelity: every oracle key (modulo
    ``KNOWN_ACTIVITY_FIDELITY_EXCEPTIONS``) must appear in the translator's
    Pydantic dump with equal value. Translator output is dumped with
    ``exclude_unset=True`` to avoid Pydantic default-value pollution."""
    failures: list[str] = []
    for key, entry in oracle.items():
        system = entry["system"]
        act = _build_activity(str(system.get("_id", "")), system)
        if act is None:
            failures.append(f"{key}: build returned None — covered by smoke test")
            continue
        # Strip the discriminator-only ``kind`` field from the comparison —
        # the oracle uses Foundry's ``type`` discriminator key, which the
        # normalizer leaves intact. We compare ``type`` against the
        # translator's pass-through copy of the same value.
        # ``by_alias=True`` so nested ``id → _id`` aliases (AppliedEffectRef,
        # SummonProfile, TransformProfile) emit the Foundry-shape key.
        actual = act.model_dump(exclude_unset=True, by_alias=True)
        # Apply the same camelCase→snake_case rewrite the translator does,
        # but WITHOUT _ACTIVITY_DROP_KEYS — the drop is what the
        # KNOWN_ACTIVITY_FIDELITY_EXCEPTIONS contract is supposed to
        # track. Passing drop_keys=frozenset() keeps `appliedEffects` (and
        # any future deferred field) in the expected dict so it can be
        # explicitly excepted, not silently absorbed.
        expected = _normalize_activity_dict(system, drop_keys=frozenset())
        # Strip the oracle's ``type`` discriminator from the expected dict;
        # the translator routes on it but does not re-emit it (the per-kind
        # class has a ``kind: Literal[…]`` field instead). Assert kind is
        # populated as a side check.
        oracle_type = expected.pop("type", None)
        if oracle_type is not None and act.kind != oracle_type:
            failures.append(
                f"{key}: kind mismatch oracle.type={oracle_type!r} actual.kind={act.kind!r}"
            )
        actual.pop("kind", None)
        local: list[str] = []
        _compare_subset(expected, actual, [], local, entry["activity_kind"])
        if local:
            failures.extend(f"{key}: {msg}" for msg in local)
    if failures:
        body = "\n".join(failures[:200])
        pytest.fail(
            f"{len(failures)} activity field-fidelity failures "
            f"(showing first 200 of {len(failures)}):\n{body}"
        )
