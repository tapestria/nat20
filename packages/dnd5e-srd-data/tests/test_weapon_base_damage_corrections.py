"""SRD 5.2 weapon base-damage corrections (translator override map).

Foundry ships the Unarmed Strike's base damage only as the roll-data formula
``@mod + @prof``, which the translator cannot carry and which is not the SRD
rule; the Rules Glossary is the ground truth. These tests pin the corrected
canonical output (hermetic) and, when raw sources are present, the
translator path and the glossary sentence that grounds it.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest

from dnd5e_srd_data import BundledAssetLoader
from dnd5e_srd_data.schema.common import DamagePart

ROOT = Path(__file__).resolve().parent.parent
PACKS = ROOT / "raw_sources" / "foundry" / "packs" / "_source"
needs_raw = pytest.mark.skipif(not PACKS.is_dir(), reason="raw_sources/foundry not populated")


def _translate(relative: str):
    from tools.translators.foundry import translate_weapon_yaml

    return translate_weapon_yaml(
        PACKS / relative, ingest_date=date(2024, 1, 1), ingest_version="test"
    )


def test_canonical_unarmed_strike_deals_one_bludgeoning() -> None:
    weapon = BundledAssetLoader().get_weapon("unarmed-strike")
    assert weapon is not None
    assert weapon.damage_parts == [DamagePart(dice="1", damage_type="bludgeoning")]


@needs_raw
def test_translator_fills_the_unarmed_strike_base_damage() -> None:
    weapon = _translate("equipment24/supplemental/unarmed-strike.yml")
    assert weapon.damage_parts == [DamagePart(dice="1", damage_type="bludgeoning")]


@needs_raw
def test_the_rules_glossary_grounds_the_correction() -> None:
    glossary = (PACKS / "content24" / "appendices" / "rules-glossary.yml").read_text()
    text = re.sub(r"\s+", " ", glossary)
    assert "Bludgeoning damage equal to 1 plus your Strength modifier" in text


@needs_raw
def test_a_weapon_with_structured_damage_is_untouched() -> None:
    weapon = _translate("equipment24/weapons/martial-melee/longsword.yml")
    assert weapon.damage_parts == [DamagePart(dice="1d8", damage_type="slashing")]
