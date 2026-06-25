from datetime import date
from pathlib import Path

import pytest
import yaml

from tools.translators.foundry import _passive_effects, translate_feature_yaml

_PACKS = Path("raw_sources/foundry/packs/_source")
_FEATURE_DIRS = [_PACKS / "classes24", _PACKS / "origins24/species/traits"]
_INGEST = dict(ingest_date=date(2026, 6, 4), ingest_version="x")
pytestmark = pytest.mark.skipif(not _PACKS.is_dir(), reason="raw_sources/foundry not populated")


def test_passive_effects_preserves_id_and_statuses():
    doc = {
        "effects": [
            {
                "_id": "PklwZi3SKQ3JU2M2",
                "name": "Paralyzed",
                "statuses": ["paralyzed"],
                "changes": [],
                "duration": {"seconds": 60},
            }
        ]
    }
    out = _passive_effects(doc)
    assert out[0].id == "PklwZi3SKQ3JU2M2"
    assert out[0].statuses == ["paralyzed"]


def _srd_feature_docs():
    for root in _FEATURE_DIRS:
        for p in sorted(root.rglob("*.yml")):
            if p.name.startswith("_"):
                continue
            doc = yaml.safe_load(p.read_text(encoding="utf-8"))
            if not isinstance(doc, dict) or doc.get("type") != "feat":
                continue
            src = (doc.get("system") or {}).get("source") or {}
            if (
                src.get("license") == "CC-BY-4.0" and src.get("rules") in ("2014", "2024")
            ) or doc.get("flags", {}).get("srd"):
                yield p, doc


def test_every_feature_effect_change_round_trips():
    failures = []
    for path, doc in _srd_feature_docs():
        raw_changes = [
            (
                c.get("key"),
                int(c.get("mode") or 0),
                "" if c.get("value") is None else str(c.get("value")),
            )
            for eff in (doc.get("effects") or [])
            for c in (eff.get("changes") or [])
            if c.get("key")
        ]
        if not raw_changes:
            continue
        feat = translate_feature_yaml(path, **_INGEST)
        got = {(c.key, c.mode, c.value) for e in feat.passive_effects for c in e.changes}
        missing = [rc for rc in raw_changes if rc not in got]
        if missing:
            failures.append((path.name, missing))
    assert not failures, f"feature passive-effect drift: {failures[:20]}"


def test_rage_passive_effect_preserves_scale_and_resistances():
    f = translate_feature_yaml(_PACKS / "classes24/barbarian/class-features/rage.yml", **_INGEST)
    changes = [c for e in f.passive_effects for c in e.changes]
    keys = {c.key for c in changes}
    assert "system.bonuses.mwak.damage" in keys
    assert "system.traits.dr.value" in keys
    scale = next(c for c in changes if c.key == "system.bonuses.mwak.damage")
    assert scale.value == "+@scale.barbarian.rage-damage"
