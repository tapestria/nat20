"""Inline monster-activity extraction from the 2024 actors24 packs.

2024 monsters are ``type: npc`` with embedded ``items[]`` (weapon/feat/…),
each carrying inline ``system.activities``. Weapon attack activities defer
their base damage to the parent item's ``system.damage.base`` via
``damage.includeBase: true``; the translator resolves that base inline.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from dnd5e_srd_data import AttackActivity
from tools.translators.foundry import translate_monster_yaml

PACKS = Path("raw_sources/foundry/packs/_source")
pytestmark = pytest.mark.skipif(not PACKS.is_dir(), reason="raw_sources/foundry not populated")

ROOT = Path(__file__).resolve().parent.parent
ACTORS = ROOT / "raw_sources" / "foundry" / "packs" / "_source" / "actors24"


def _translate(rel: str):
    return translate_monster_yaml(
        yaml_path=ACTORS / rel,
        ingest_date=date(2024, 1, 1),
        ingest_version="test",
    )


def test_ape_attack_activities_resolved() -> None:
    monster = _translate("beast/ape.yml")

    by_name = {a.name: a for a in monster.actions}
    assert {"Fist", "Rock"} <= set(by_name), by_name.keys()

    for weapon_name in ("Fist", "Rock"):
        action = by_name[weapon_name]
        attacks = [a for a in action.activities if isinstance(a, AttackActivity)]
        assert attacks, f"{weapon_name} has no AttackActivity"
        attack = attacks[0]
        # includeBase weapon attacks resolve the parent item base damage inline.
        assert attack.damage.parts, f"{weapon_name} attack has no resolved damage"
        part = attack.damage.parts[0]
        assert part.number
        assert part.denomination
        assert part.types


def test_ape_resolved_damage_values() -> None:
    monster = _translate("beast/ape.yml")
    by_name = {a.name: a for a in monster.actions}

    fist = next(a for a in by_name["Fist"].activities if isinstance(a, AttackActivity))
    assert (fist.damage.parts[0].number, fist.damage.parts[0].denomination) == (1, 4)
    assert fist.damage.parts[0].types == ["bludgeoning"]

    rock = next(a for a in by_name["Rock"].activities if isinstance(a, AttackActivity))
    assert (rock.damage.parts[0].number, rock.damage.parts[0].denomination) == (2, 6)


def test_wight_mixed_base_and_rider_damage() -> None:
    """Wight's Necrotic Sword carries BOTH a base weapon part (slashing 1d8 via
    ``system.damage.base`` + ``includeBase: true``) AND a rider part (necrotic
    1d8 in the activity's ``damage.parts``). The resolver must keep both — base
    first, then riders — not drop the base just because riders are present."""
    monster = _translate("undead/wight.yml")
    by_name = {a.name: a for a in monster.actions}
    assert "Necrotic Sword" in by_name, by_name.keys()

    attack = next(a for a in by_name["Necrotic Sword"].activities if isinstance(a, AttackActivity))
    type_to_dice = {
        tuple(part.types): (part.number, part.denomination) for part in attack.damage.parts
    }
    # Base weapon damage (slashing) must survive alongside the necrotic rider.
    assert ("slashing",) in type_to_dice, attack.damage.parts
    assert ("necrotic",) in type_to_dice, attack.damage.parts
    assert type_to_dice[("slashing",)] == (1, 8)
    assert type_to_dice[("necrotic",)] == (1, 8)
    # Deterministic ordering: base part precedes riders.
    assert attack.damage.parts[0].types == ["slashing"]
