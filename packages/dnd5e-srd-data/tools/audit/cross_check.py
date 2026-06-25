"""Flat-field cross-check between Foundry-translated canonical entries and
the 5e-bits/open5e SRD oracle.

Advisory only. Emits findings to ``audit/validation_report.json``; canonical
output is not modified. Reviewer triages periodically and records resolutions
via inline ``review.known_divergence`` or via
``tests/oracle/known_oracle_divergence.json`` for the gate test.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
ORACLE_DIR = ROOT / "tests" / "oracle"


@dataclass(frozen=True)
class CrossCheckFinding:
    slug: str
    kind: str  # "monster" | "item"
    field: str
    canonical_value: Any
    oracle_value: Any


def _load_oracle(name: str) -> dict[str, Any]:
    path = ORACLE_DIR / name
    if not path.is_file():
        return {}
    loaded: Any = json.loads(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def _monster_oracle() -> dict[str, Any]:
    return _load_oracle("srd_monster_oracle.json")


def _item_oracle() -> dict[str, Any]:
    return _load_oracle("srd_item_oracle.json")


def diff_monster_flat_fields(
    slug: str,
    canonical: dict[str, Any],
    oracle: dict[str, Any] | None = None,
) -> list[CrossCheckFinding]:
    """Find divergences where canonical disagrees with the SRD oracle on a
    flat field. ``None`` on either side is treated as 'no signal' (skip)."""
    if oracle is None:
        oracle = _monster_oracle().get(slug) or {}
    if not oracle:
        return []
    findings: list[CrossCheckFinding] = []

    def check(field: str, canonical_val: Any, oracle_val: Any) -> None:
        if oracle_val is None:
            return
        if canonical_val is None:
            # Canonical-missing is a real gap; record it.
            findings.append(CrossCheckFinding(slug, "monster", field, canonical_val, oracle_val))
            return
        if canonical_val != oracle_val:
            findings.append(CrossCheckFinding(slug, "monster", field, canonical_val, oracle_val))

    check("hp", canonical.get("hp"), oracle.get("hp"))
    check("cr", canonical.get("cr"), oracle.get("cr"))
    # AC mismatch is only a finding when canonical has a concrete value that
    # disagrees with oracle. canonical=null means "Foundry didn't ship a flat
    # AC; runtime derives it from equipped armor". That's a known deferred
    # gap (documented in CLAUDE-style note), not a Foundry-vs-open5e
    # disagreement worth surfacing in the report each regen.
    if canonical.get("ac") is not None:
        check("ac", canonical.get("ac"), oracle.get("ac"))
    check("proficiency_bonus", canonical.get("proficiency_bonus"), oracle.get("proficiency_bonus"))
    return findings


def diff_item_flat_fields(
    slug: str,
    canonical: dict[str, Any],
    oracle: dict[str, Any] | None = None,
) -> list[CrossCheckFinding]:
    if oracle is None:
        oracle = _item_oracle().get(slug) or {}
    if not oracle:
        return []
    findings: list[CrossCheckFinding] = []

    def check(field: str, canonical_val: Any, oracle_val: Any) -> None:
        if oracle_val is None:
            return
        if canonical_val != oracle_val:
            findings.append(CrossCheckFinding(slug, "item", field, canonical_val, oracle_val))

    # Only assert weight when the oracle has a real value; magic items in
    # 5e-bits don't ship weight at all (defaults to 0 in the oracle).
    if oracle.get("weight"):
        check("weight", float(canonical.get("weight") or 0), float(oracle["weight"]))
    check("cost_gp", canonical.get("cost_gp"), oracle.get("cost_gp"))
    if oracle.get("kind") == "weapon":
        parts = canonical.get("damage_parts") or []
        c_dice = parts[0]["dice"] if parts else None
        c_type = parts[0]["damage_type"] if parts else None
        check("damage_dice", c_dice, oracle.get("damage_dice"))
        check("damage_type", c_type, oracle.get("damage_type"))
    if oracle.get("kind") == "armor":
        check("base_ac", canonical.get("base_ac"), oracle.get("base_ac"))
    if "rarity" in oracle and oracle.get("rarity"):
        check("rarity", canonical.get("rarity"), oracle.get("rarity"))
    return findings


def diff_spell_flat_fields(
    slug: str,
    canonical: dict[str, Any],
    oracle: dict[str, Any] | None = None,
) -> list[CrossCheckFinding]:
    if oracle is None:
        oracle = _load_oracle("srd_spell_oracle.json").get(slug) or {}
    if not oracle:
        return []
    findings: list[CrossCheckFinding] = []

    def check(field: str, canonical_val: Any, oracle_val: Any) -> None:
        if oracle_val is None:
            return
        if canonical_val != oracle_val:
            findings.append(CrossCheckFinding(slug, "spell", field, canonical_val, oracle_val))

    check("level", canonical.get("level"), oracle.get("level"))
    check("school", canonical.get("school"), oracle.get("school"))
    check("ritual", canonical.get("ritual"), oracle.get("ritual"))
    check("concentration", canonical.get("concentration"), oracle.get("concentration"))
    if oracle.get("components"):
        check("components", sorted(canonical.get("components") or []), oracle.get("components"))
    expected_ct = oracle.get("casting_time")
    actual_ct = canonical.get("casting_time") or {}
    if expected_ct:
        ct_tuple = (actual_ct.get("value"), actual_ct.get("unit"))
        # Oracle ships (value, unit) as a list after JSON round-trip.
        if list(ct_tuple) != list(expected_ct):
            findings.append(
                CrossCheckFinding(slug, "spell", "casting_time", list(ct_tuple), expected_ct)
            )
    expected_range = oracle.get("range") or {}
    actual_range = canonical.get("range") or {}
    if expected_range.get("units"):
        check("range.units", actual_range.get("units"), expected_range.get("units"))
        if expected_range.get("value") is not None:
            check("range.value", actual_range.get("value"), expected_range.get("value"))
    expected_dur = oracle.get("duration") or {}
    actual_dur = canonical.get("duration") or {}
    if expected_dur.get("units"):
        check("duration.units", actual_dur.get("units"), expected_dur.get("units"))
        if expected_dur.get("value") is not None:
            check("duration.value", actual_dur.get("value"), expected_dur.get("value"))
    return findings


def diff_species_flat_fields(
    slug: str,
    canonical: dict[str, Any],
    oracle: dict[str, Any] | None = None,
) -> list[CrossCheckFinding]:
    if oracle is None:
        oracle = _load_oracle("srd_species_oracle.json").get(slug) or {}
    if not oracle:
        return []
    findings: list[CrossCheckFinding] = []

    def check(field: str, canonical_val: Any, oracle_val: Any) -> None:
        if oracle_val is None:
            return
        if canonical_val != oracle_val:
            findings.append(CrossCheckFinding(slug, "species", field, canonical_val, oracle_val))

    check("size", canonical.get("size"), oracle.get("size"))
    if oracle.get("speed") is not None:
        check("walk_speed", (canonical.get("movement") or {}).get("walk"), oracle.get("speed"))
    return findings


def diff_class_flat_fields(
    slug: str,
    canonical: dict[str, Any],
    oracle: dict[str, Any] | None = None,
) -> list[CrossCheckFinding]:
    if oracle is None:
        oracle = _load_oracle("srd_class_oracle.json").get(slug) or {}
    if not oracle:
        return []
    findings: list[CrossCheckFinding] = []
    expected_hd = oracle.get("hit_die")
    actual_hd = canonical.get("hit_die")
    # Foundry hit_die is a string ("d10"); oracle ships int (10).
    if expected_hd is not None and actual_hd is not None:
        actual_int = int(str(actual_hd).removeprefix("d") or 0)
        if actual_int != expected_hd:
            findings.append(CrossCheckFinding(slug, "class", "hit_die", actual_int, expected_hd))
    return findings


def diff_subclass_flat_fields(
    slug: str,
    canonical: dict[str, Any],
    oracle: dict[str, Any] | None = None,
) -> list[CrossCheckFinding]:
    if oracle is None:
        oracle = _load_oracle("srd_subclass_oracle.json").get(slug) or {}
    if not oracle:
        return []
    findings: list[CrossCheckFinding] = []
    expected_class = oracle.get("class_slug")
    actual_class = canonical.get("class_identifier")
    if expected_class and actual_class and expected_class != actual_class:
        findings.append(
            CrossCheckFinding(slug, "subclass", "class_identifier", actual_class, expected_class)
        )
    return findings


def finding_to_jsonable(f: CrossCheckFinding) -> dict[str, Any]:
    return asdict(f)
