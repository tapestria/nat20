"""Cluster 5 (Spatial) — cover-bonus consumers not exercised by the e2e
catalog: the Dexterity-save fold (SRD 5.2 §Cover applies the SAME +2/+5 to
"AC and Dexterity saving throws") and a focused resolver-seam check on the
AC fold (C05-S02/S03 already cover the AC path end to end via
``submit_player_intent``; this pins the narrower consumption seam directly,
mirroring ``tests/test_weapon_damage_bonus_sidecar.py``'s pattern).

``ActivityResolutionContext.target_cover`` is the sidecar both consumers
read: ``activities/attack.py::resolve_attack`` (AC) and
``activities/save_primitive.py::roll_save`` (Dexterity saves only).
"""

from __future__ import annotations

import random

from dnd5e_srd_data.loader import BundledAssetLoader

from dnd5e_engine.activities.context import ActivityResolutionContext
from dnd5e_engine.activities.resolver import resolve_activity
from dnd5e_engine.activities.save_primitive import roll_save
from dnd5e_engine.events import AttackRolled
from dnd5e_engine.types.combat import Combatant

# ── save_primitive.roll_save: direct unit tests (pure function) ─────────────


def _target(ac: int = 10) -> Combatant:
    return Combatant(
        entity_id="mon:foe",
        entity_type="Monster",
        name="Foe",
        initiative=1,
        hp_current=50,
        hp_max=50,
        ac=ac,
    )


def _ctx(target_cover: dict[str, str]) -> ActivityResolutionContext:
    return ActivityResolutionContext(
        rng=random.Random(1),
        caster=Combatant(
            entity_id="char:hero",
            entity_type="Character",
            name="Hero",
            initiative=10,
            hp_current=20,
            hp_max=20,
        ),
        targets=[],
        event_emitter=lambda ev: None,
        caster_abilities={"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10},
        target_cover=target_cover,
        variables={"force_save_d20": 10},
    )


def test_dex_save_gains_half_cover_bonus():
    target = _target()
    total_no_cover, _ = roll_save(_ctx({}), target, "dex", dc=15)
    total_half_cover, _ = roll_save(_ctx({"mon:foe": "half"}), target, "dex", dc=15)
    assert total_half_cover == total_no_cover + 2


def test_dex_save_gains_three_quarters_cover_bonus():
    target = _target()
    total_no_cover, _ = roll_save(_ctx({}), target, "dex", dc=15)
    total_boosted, _ = roll_save(_ctx({"mon:foe": "three_quarters"}), target, "dex", dc=15)
    assert total_boosted == total_no_cover + 5


def test_cover_bonus_flips_dex_save_failure_to_success():
    target = _target()
    # natural 10 + 0 mod == 10 < dc 12 -> fails without cover.
    total, succeeded = roll_save(_ctx({}), target, "dex", dc=12)
    assert total == 10
    assert succeeded is False
    # +2 half cover -> 12 >= dc 12 -> succeeds.
    total_cover, succeeded_cover = roll_save(_ctx({"mon:foe": "half"}), target, "dex", dc=12)
    assert total_cover == 12
    assert succeeded_cover is True


def test_non_dex_save_is_unaffected_by_cover():
    target = _target()
    total_no_cover, _ = roll_save(_ctx({}), target, "con", dc=15)
    total_with_cover_tag, _ = roll_save(_ctx({"mon:foe": "total"}), target, "con", dc=15)
    assert total_with_cover_tag == total_no_cover  # cover is AC/DEX-save only


def test_absent_target_cover_entry_contributes_zero():
    target = _target()
    total, _ = roll_save(_ctx({"mon:someone_else": "total"}), target, "dex", dc=15)
    total_none, _ = roll_save(_ctx({}), target, "dex", dc=15)
    assert total == total_none


# ── attack.py: resolver-seam check on the AC fold ────────────────────────────


def _rolled_attack(target_cover: dict[str, str], *, target_ac: int) -> AttackRolled:
    loader = BundledAssetLoader()
    longsword = loader.get_weapon("longsword")
    assert longsword is not None
    activity = next(a for a in longsword.activities if a.kind == "attack")

    attacker = Combatant(
        entity_id="char:hero",
        entity_type="Character",
        name="Hero",
        initiative=10,
        hp_current=20,
        hp_max=20,
        strength=16,
    )
    target = Combatant(
        entity_id="mon:foe",
        entity_type="Monster",
        name="Foe",
        initiative=1,
        hp_current=500,
        hp_max=500,
        ac=target_ac,
    )
    events: list = []
    ctx = ActivityResolutionContext(
        rng=random.Random(1),
        caster=attacker,
        targets=[target],
        event_emitter=events.append,
        caster_abilities={"str": 16, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10},
        caster_proficiency_bonus=2,
        caster_level=1,
        target_cover=target_cover,
        variables={"force_d20": 8},  # natural 8 + str mod(3) + prof(2) = 13
    )
    resolve_activity(activity, ctx, weapon=longsword)
    return next(e for e in events if isinstance(e, AttackRolled))


def test_half_cover_raises_effective_ac_flipping_a_hit_to_a_miss():
    # roll_total is 13 (forced): hits AC 12, misses AC 12+2=14 with half cover.
    hit_no_cover = _rolled_attack({}, target_ac=12)
    miss_with_cover = _rolled_attack({"mon:foe": "half"}, target_ac=12)
    assert hit_no_cover.is_hit is True
    assert miss_with_cover.is_hit is False
    assert (
        hit_no_cover.roll_total == miss_with_cover.roll_total == 13
    )  # cover never touches the roll


def test_absent_attacker_target_cover_entry_behaves_as_no_cover():
    rolled = _rolled_attack({"mon:someone_else": "total"}, target_ac=12)
    assert rolled.is_hit is True  # unaffected — the key doesn't match this target
