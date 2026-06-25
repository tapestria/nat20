import json
from pathlib import Path

ORACLE = Path("tests/oracle/activity_oracle.json")


def test_oracle_covers_feature_activities():
    data = json.loads(ORACLE.read_text())
    keys = set(data)
    assert any(k.startswith("classes24/barbarian/class-features/rage#") for k in keys), (
        "Rage activity missing from oracle"
    )
    assert any("rogue/class-features/sneak-attack#" in k for k in keys)


def test_oracle_keys_are_path_based():
    data = json.loads(ORACLE.read_text())
    assert all("/" in k.split("#", 1)[0] for k in data), "oracle keys must be path-based"
