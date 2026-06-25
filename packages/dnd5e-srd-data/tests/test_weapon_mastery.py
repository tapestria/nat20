"""Weapon mastery extraction from the 2024 equipment24 packs.

2024 SRD weapons carry a flat ``system.mastery`` slug (e.g. "sap", "graze",
"nick"); the empty string and absence both mean "no mastery" → None.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from tools.translators.foundry import translate_weapon_yaml

PACKS = Path("raw_sources/foundry/packs/_source")
pytestmark = pytest.mark.skipif(not PACKS.is_dir(), reason="raw_sources/foundry not populated")

ROOT = Path(__file__).resolve().parent.parent
WEAPONS = ROOT / "raw_sources" / "foundry" / "packs" / "_source" / "equipment24" / "weapons"


def _translate(rel: str):
    return translate_weapon_yaml(
        yaml_path=WEAPONS / rel,
        ingest_date=date(2024, 1, 1),
        ingest_version="test",
    )


@pytest.mark.parametrize(
    ("rel", "expected"),
    [
        ("martial-melee/longsword.yml", "sap"),
        ("martial-melee/greatsword.yml", "graze"),
        ("simple-melee/dagger.yml", "nick"),
        ("simple-melee/club.yml", "slow"),
    ],
)
def test_weapon_mastery_extracted(rel: str, expected: str) -> None:
    weapon = _translate(rel)
    assert weapon.mastery == expected


def test_weapon_without_mastery_is_none() -> None:
    # unarmed-strike ships ``mastery: ''`` → None.
    weapon = _translate("unarmed-strike.yml")
    assert weapon.mastery is None
