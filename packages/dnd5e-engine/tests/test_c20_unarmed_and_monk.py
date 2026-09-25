"""Unarmed Strike, Martial Arts and the Monk's bonus-funded strikes (SRD 5.2)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from dnd5e_srd_data.loader import BundledAssetLoader

from dnd5e_engine.events import AttackRolled, DamageApplied
from dnd5e_engine.lib_loader import set_lib_loader_for_tests
from tests.c20_support import act, events, pc, start


@pytest.fixture(autouse=True)
def _bundled_loader() -> Iterator[None]:
    set_lib_loader_for_tests(BundledAssetLoader())
    yield
    set_lib_loader_for_tests(None)


def _unarmed(handle, actor: str = "char:hero", **intent) -> None:
    act(
        handle,
        actor,
        intent_type="attack",
        weapon_id="unarmed-strike",
        target_id="mon:foe",
        **intent,
    )


# ── Task 2 — Unarmed Strike base damage ──────────────────────────────────────


def test_unarmed_strike_deals_one_plus_strength() -> None:
    """SRD 5.2 Unarmed Strike: "On a hit, the target takes Bludgeoning damage
    equal to 1 plus your Strength modifier." Seed 2: d20 2 + STR 3 + PB 2 = 7
    hits AC 1; the damage is 1 + 3 = 4 and no damage die is drawn."""
    handle, live = start([pc(strength=16)], seed=2)
    _unarmed(handle)
    [hit] = events(live, DamageApplied)
    assert (hit.amount, hit.damage_type, hit.source_id) == (4, "bludgeoning", "unarmed-strike")


def test_a_critical_unarmed_strike_has_no_die_to_double() -> None:
    """Seed 5: a natural 20. "1 plus your Strength modifier" carries no die,
    so the Critical Hit deals the same 4."""
    handle, live = start([pc(strength=16)], seed=5)
    _unarmed(handle)
    [attack] = events(live, AttackRolled)
    assert attack.is_crit
    assert [e.amount for e in events(live, DamageApplied)] == [4]
