"""Build the activity fidelity oracle.

Walks every Foundry source YAML under ``raw_sources/foundry/packs/_source/``
in the canonical 2024 packs (spells24 + equipment24 + feats24 + classes24 +
origins24/species/traits) that ships a top-level ``system.activities`` block
and captures the raw activity subtree keyed by the doc's POSIX path relative
to the packs ``_source`` root (without extension) plus ``#<activity_id>``.
The path-based key prevents collisions between duplicate stems that recur
across the class tree (e.g. spellcasting, fighting-style, epic-boon).
Monster (actors24) activities are nested in ``items[].system.activities`` and
are covered by the monster translator test.

The oracle is the answer key for the translator's per-kind builders: every
field present in a Foundry activity subtree MUST round-trip through the
translator's ``Activity`` Pydantic models without loss. The fidelity tests
(``tests/test_translator_fidelity.py``) consume this artifact.

Output: ``tests/oracle/activity_oracle.json``. Schema::

    {
        "<rel/posix/path>#<activity_id>": {
            "entity_kind": "weapon" | "spell" | "equipment" | ...,
            "activity_kind": "attack" | "save" | "damage" | ...,
            "system": { ...raw activity dict, as loaded from Foundry YAML... }
        },
        ...
    }

Determinism: keys are sorted; JSON written with ``sort_keys=True`` so the
artifact is regen-stable for the A7 clean-tree gate.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
FOUNDRY_PACKS = ROOT / "raw_sources" / "foundry" / "packs" / "_source"
OUT_PATH = ROOT / "tests" / "oracle" / "activity_oracle.json"

# Subtrees whose activities the translator IS responsible for. Canonical now
# comes from the 2024 SRD packs; these carry their activities at the top-level
# ``system.activities`` key.
#
# actors24 (monsters) is deferred here: 2024 monster activities live nested in
# ``items[].system.activities`` (not the top-level shape this builder walks), so
# adding them would require reworking the traversal. It's safe to defer because
# monster activities are already validated by the per-monster translator test
# (tests/test_monster_activities.py) plus translator-fidelity.
TRANSLATED_SUBTREES = [
    "spells24",
    "equipment24",
    "feats24",
    "classes24",
    "origins24/species/traits",
]


def build_oracle() -> dict[str, dict[str, Any]]:
    oracle: dict[str, dict[str, Any]] = {}
    yaml_paths: list[Path] = []
    for sub in TRANSLATED_SUBTREES:
        root = FOUNDRY_PACKS / sub
        if root.is_dir():
            yaml_paths.extend(sorted(root.rglob("*.yml")))
    for yaml_path in yaml_paths:
        if yaml_path.name.startswith("_"):
            continue
        try:
            doc = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001  # malformed YAML — skip in audit
            continue
        if not isinstance(doc, dict):
            continue
        system = doc.get("system")
        if not isinstance(system, dict):
            continue
        activities = system.get("activities")
        if not isinstance(activities, dict):
            continue
        entity_kind = str(doc.get("type") or "unknown")
        rel = yaml_path.relative_to(FOUNDRY_PACKS).with_suffix("").as_posix()
        for activity_id, activity in activities.items():
            if not isinstance(activity, dict):
                continue
            activity_kind = str(activity.get("type") or "unknown")
            key = f"{rel}#{activity_id}"
            if key in oracle:
                raise RuntimeError(f"activity oracle key collision: {key}")
            oracle[key] = {
                "entity_kind": entity_kind,
                "activity_kind": activity_kind,
                "system": activity,
            }
    return {k: oracle[k] for k in sorted(oracle.keys())}


def main() -> int:
    oracle = build_oracle()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(oracle, indent=2, sort_keys=True), encoding="utf-8")
    print(f"[activity_oracle] wrote {OUT_PATH} ({len(oracle)} activities)")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
