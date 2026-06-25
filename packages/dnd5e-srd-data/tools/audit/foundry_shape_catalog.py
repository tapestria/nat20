"""Walk every Foundry pack YAML under ``raw_sources/foundry/packs/_source/``
and catalog every ``system.*`` (and ``traits.*``) field path with its observed
value-shape variants.

Output: ``audit/foundry_shape_catalog.json``. Schema per entry::

    "<doc_type>.<dotted.path>": {
        "type_variants": ["NoneType", "int", "str", "dict{value,units}", ...],
        "sample_values": [...up to 3 examples per variant...],
        "occurrences": 123,
        "example_slugs": ["longsword", ...]
    }

With ``--activities``, focus on ``system.activities[*]`` subtrees, keyed by
``<entity_kind>.<activity_kind>.<dotted.path>`` with ``example_refs``
(``slug#activity_id``) instead of ``example_slugs``. Output:
``audit/activity_shape_catalog.json``.

This artifact is the "what does Foundry actually look like" oracle the
translator must handle. Variance discovery first; no guessing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
FOUNDRY_PACKS = ROOT / "raw_sources" / "foundry" / "packs" / "_source"
AUDIT_DIR = ROOT / "audit"

# Only walk the subtrees the translator currently consumes. Adding more later
# is one constant edit.
INTERESTING_SUBTREES = [
    "items",
    "monsters",
    "spells",
    "classes",
    "subclasses",
    "classfeatures",
    "origins24",
]

# Max depth we recurse into nested dicts. Foundry packs go ~6 deep; 8 is safe.
MAX_DEPTH = 8

# Per-variant cap to keep the catalog readable.
MAX_SAMPLES_PER_VARIANT = 3
MAX_EXAMPLES_PER_PATH = 5

# Activity-mode caps: deeper sampling so A3 schema design has enough variance.
ACTIVITY_MAX_SAMPLES_PER_VARIANT = 6
ACTIVITY_MAX_EXAMPLES_PER_PATH = 10


def _shape_tag(value: Any) -> str:
    """Compact one-line description of a value's shape."""
    if value is None:
        return "NoneType"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        if value == "":
            return "str(empty)"
        return "str"
    if isinstance(value, list):
        if not value:
            return "list(empty)"
        elem = _shape_tag(value[0])
        return f"list<{elem}>"
    if isinstance(value, dict):
        if not value:
            return "dict(empty)"
        keys = sorted(value.keys())
        return "dict{" + ",".join(keys) + "}"
    return type(value).__name__


def _record(
    catalog: dict[str, dict[str, Any]],
    key: str,
    value: Any,
    example_ref: str,
    examples_field: str,
    samples_cap: int,
    examples_cap: int,
) -> None:
    """Record one (path, value, example) observation."""
    shape = _shape_tag(value)
    entry = catalog.setdefault(
        key,
        {"type_variants": {}, "occurrences": 0, examples_field: []},
    )
    entry["occurrences"] += 1
    variants: dict[str, list[Any]] = entry["type_variants"]
    samples = variants.setdefault(shape, [])
    if len(samples) < samples_cap and value not in samples:
        # Truncate long strings/lists in samples for readability; skip dict
        # contents because the shape tag already encoded the keys.
        if isinstance(value, str) and len(value) > 80:
            samples.append(value[:77] + "...")
        elif isinstance(value, list) and len(value) > 6:
            samples.append(value[:6] + ["..."])
        elif isinstance(value, dict):
            pass
        else:
            samples.append(value)
    examples = entry[examples_field]
    if example_ref not in examples and len(examples) < examples_cap:
        examples.append(example_ref)


def _walk(
    catalog: dict[str, dict[str, Any]],
    *,
    key_prefix: str,
    example_ref: str,
    examples_field: str,
    samples_cap: int,
    examples_cap: int,
    path: str,
    value: Any,
    depth: int,
) -> None:
    """Recurse into ``value`` recording every (key_prefix.path) observation.

    Lists: descend into the FIRST element (most lists are homogeneous —
    weapon.properties: list<str>, abilities: list<dict>)."""
    key = f"{key_prefix}.{path}" if path else key_prefix
    _record(catalog, key, value, example_ref, examples_field, samples_cap, examples_cap)
    if depth >= MAX_DEPTH:
        return
    if isinstance(value, dict):
        for k, v in value.items():
            _walk(
                catalog,
                key_prefix=key_prefix,
                example_ref=example_ref,
                examples_field=examples_field,
                samples_cap=samples_cap,
                examples_cap=examples_cap,
                path=f"{path}.{k}" if path else k,
                value=v,
                depth=depth + 1,
            )
    elif isinstance(value, list) and value and isinstance(value[0], (dict, list)):
        _walk(
            catalog,
            key_prefix=key_prefix,
            example_ref=example_ref,
            examples_field=examples_field,
            samples_cap=samples_cap,
            examples_cap=examples_cap,
            path=path + "[0]",
            value=value[0],
            depth=depth + 1,
        )


def _iter_pack_docs() -> list[tuple[Path, dict[str, Any]]]:
    """Load every YAML doc in ``INTERESTING_SUBTREES`` as (path, parsed dict).
    Skips ``_*.yml`` directory-metadata files and malformed YAML."""
    out: list[tuple[Path, dict[str, Any]]] = []
    for sub in INTERESTING_SUBTREES:
        root = FOUNDRY_PACKS / sub
        if not root.is_dir():
            continue
        for yaml_path in sorted(root.rglob("*.yml")):
            if yaml_path.name.startswith("_"):
                continue
            try:
                doc = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001  # malformed YAML — skip in audit
                continue
            if isinstance(doc, dict):
                out.append((yaml_path, doc))
    return out


def _finalize(catalog: dict[str, dict[str, Any]], examples_field: str) -> dict[str, dict[str, Any]]:
    """Stable-sort + freeze variant dicts into JSON-ready shape."""
    out: dict[str, dict[str, Any]] = {}
    for key in sorted(catalog.keys()):
        e = catalog[key]
        variants = e["type_variants"]
        out[key] = {
            "type_variants": sorted(variants.keys()),
            "sample_values": {v: variants[v] for v in sorted(variants.keys())},
            "occurrences": e["occurrences"],
            examples_field: e[examples_field],
        }
    return out


def build_catalog() -> dict[str, dict[str, Any]]:
    """Walk ``system.*`` across SRD-eligible Foundry sources, keyed by
    ``<doc_type>.system.<dotted.path>``."""
    catalog: dict[str, dict[str, Any]] = {}
    for yaml_path, doc in _iter_pack_docs():
        doc_type = str(doc.get("type") or "unknown")
        slug = yaml_path.stem
        system = doc.get("system")
        if not isinstance(system, dict):
            continue
        for k, v in system.items():
            _walk(
                catalog,
                key_prefix=doc_type,
                example_ref=slug,
                examples_field="example_slugs",
                samples_cap=MAX_SAMPLES_PER_VARIANT,
                examples_cap=MAX_EXAMPLES_PER_PATH,
                path=f"system.{k}",
                value=v,
                depth=1,
            )
    return _finalize(catalog, "example_slugs")


def build_activity_catalog() -> dict[str, dict[str, Any]]:
    """Walk ``system.activities[*]`` across SRD-eligible Foundry sources,
    keyed by ``<entity_kind>.<activity_kind>.<dotted.path>``."""
    catalog: dict[str, dict[str, Any]] = {}
    for yaml_path, doc in _iter_pack_docs():
        entity_kind = str(doc.get("type") or "unknown")
        slug = yaml_path.stem
        system = doc.get("system")
        if not isinstance(system, dict):
            continue
        activities = system.get("activities")
        if not isinstance(activities, dict):
            continue
        for activity_id, activity in activities.items():
            if not isinstance(activity, dict):
                continue
            activity_kind = str(activity.get("type") or "unknown")
            key_prefix = f"{entity_kind}.{activity_kind}"
            ref = f"{slug}#{activity_id}"
            for k, v in activity.items():
                _walk(
                    catalog,
                    key_prefix=key_prefix,
                    example_ref=ref,
                    examples_field="example_refs",
                    samples_cap=ACTIVITY_MAX_SAMPLES_PER_VARIANT,
                    examples_cap=ACTIVITY_MAX_EXAMPLES_PER_PATH,
                    path=k,
                    value=v,
                    depth=1,
                )
    return _finalize(catalog, "example_refs")


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--activities",
        action="store_true",
        help="Profile only system.activities[*] subtrees; write activity_shape_catalog.json.",
    )
    args = parser.parse_args()

    AUDIT_DIR.mkdir(exist_ok=True)
    if args.activities:
        catalog = build_activity_catalog()
        out_path = AUDIT_DIR / "activity_shape_catalog.json"
        out_path.write_text(json.dumps(catalog, indent=2, sort_keys=True), encoding="utf-8")
        print(f"[activity_shape_catalog] wrote {out_path} ({len(catalog)} field paths)")
        return 0
    catalog = build_catalog()
    out_path = AUDIT_DIR / "foundry_shape_catalog.json"
    out_path.write_text(json.dumps(catalog, indent=2, sort_keys=True), encoding="utf-8")
    print(f"[shape_catalog] wrote {out_path} ({len(catalog)} field paths)")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
