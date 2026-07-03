"""C07-S01/S02/S04 — focused unit tests on the Sneak Attack resolver seam.

The end-to-end scenarios live in
``tests/e2e/test_c07_sneak_and_repertoire.py``; these pin the pure-resolver
pieces directly (mirroring the ``passive_*`` sidecar test precedent):

* attacker-side ``flags.advantage.attack`` / ``flags.disadvantage.attack``
  detection (``attacker_advantage_flags``);
* the Finesse-or-Ranged + Advantage-or-ally-adjacent trigger predicate
  (``sneak_attack_triggers``);
* the ``@scale``-resolved dice lookup (``sneak_attack_dice``);
* the once-per-turn gate + the ally-adjacent alternative folded through
  ``resolve_attack`` against a guaranteed-hit target.
"""

from __future__ import annotations

import random

from dnd5e_srd_data.loader import BundledAssetLoader

from dnd5e_engine.activities.attack import (
    attacker_advantage_flags,
    sneak_attack_dice,
    sneak_attack_triggers,
)
from dnd5e_engine.activities.context import ActivityResolutionContext
from dnd5e_engine.activities.resolver import resolve_activity
from dnd5e_engine.events import DamageApplied
from dnd5e_engine.types.combat import Combatant
from dnd5e_engine.types.effects import ActiveEffect, ActiveEffectChange

_ROGUE = Combatant(
    entity_id="char:rogue",
    entity_type="Character",
    name="Rogue",
    initiative=10,
    hp_current=20,
    hp_max=20,
)


def _flag_effect(key: str, *, target_id: str = "char:rogue") -> ActiveEffect:
    return ActiveEffect(
        id=f"effect:{key}",
        name=key,
        origin="test",
        target_id=target_id,
        changes=[ActiveEffectChange(key=key, mode="override", value=True)],
    )


def _ctx(**overrides: object) -> ActivityResolutionContext:
    base: dict[str, object] = {
        "rng": random.Random(9),
        "caster": _ROGUE,
        "targets": [],
        "event_emitter": (lambda _e: None),
        "caster_abilities": {"str": 10, "dex": 18, "con": 10, "int": 10, "wis": 10, "cha": 10},
        "caster_proficiency_bonus": 3,
        "caster_level": 5,
        "scale_values": {"rogue.sneak-attack": "3d6"},
    }
    base.update(overrides)
    return ActivityResolutionContext(**base)  # type: ignore[arg-type]


# ── attacker_advantage_flags ─────────────────────────────────────────────────


def test_advantage_flag_detected_only_for_casters_own_effect():
    ctx = _ctx(active_effects=(_flag_effect("flags.advantage.attack"),))
    assert attacker_advantage_flags(ctx) == (True, False)


def test_advantage_flag_on_a_different_target_is_ignored():
    other = _flag_effect("flags.advantage.attack", target_id="char:someone-else")
    assert attacker_advantage_flags(_ctx(active_effects=(other,))) == (False, False)


def test_advantage_and_disadvantage_cancel_to_normal():
    effs = (
        _flag_effect("flags.advantage.attack"),
        _flag_effect("flags.disadvantage.attack"),
    )
    assert attacker_advantage_flags(_ctx(active_effects=effs)) == (False, False)


def test_no_effects_is_normal():
    assert attacker_advantage_flags(_ctx()) == (False, False)


# ── sneak_attack_dice ────────────────────────────────────────────────────────


def test_sneak_attack_dice_reads_scale_value():
    assert sneak_attack_dice(_ctx()) == "3d6"


def test_sneak_attack_dice_absent_when_no_scale_value():
    assert sneak_attack_dice(_ctx(scale_values={})) is None


# ── sneak_attack_triggers ────────────────────────────────────────────────────


def _dagger():
    weapon = BundledAssetLoader().get_weapon("dagger")
    assert weapon is not None
    return weapon


def _foe():
    return Combatant(
        entity_id="mon:foe",
        entity_type="Monster",
        name="Foe",
        initiative=1,
        hp_current=500,
        hp_max=500,
        ac=1,
    )


def test_trigger_fires_on_advantage_with_finesse_weapon():
    assert sneak_attack_triggers(
        _ctx(), _dagger(), _foe(), attacker_has_advantage=True, attacker_has_disadvantage=False
    )


def test_trigger_fires_on_ally_adjacent_without_advantage():
    ctx = _ctx(sneak_attack_ally_adjacent={"mon:foe": True})
    assert sneak_attack_triggers(
        ctx, _dagger(), _foe(), attacker_has_advantage=False, attacker_has_disadvantage=False
    )


def test_ally_adjacent_alternative_suppressed_by_disadvantage():
    ctx = _ctx(sneak_attack_ally_adjacent={"mon:foe": True})
    assert not sneak_attack_triggers(
        ctx, _dagger(), _foe(), attacker_has_advantage=False, attacker_has_disadvantage=True
    )


def test_no_trigger_without_advantage_or_ally():
    assert not sneak_attack_triggers(
        _ctx(), _dagger(), _foe(), attacker_has_advantage=False, attacker_has_disadvantage=False
    )


def test_spell_attack_never_qualifies():
    assert not sneak_attack_triggers(
        _ctx(), None, _foe(), attacker_has_advantage=True, attacker_has_disadvantage=False
    )


# ── end-to-end fold through resolve_attack (guaranteed hit) ──────────────────


def _swing_total(*, active_effects=(), sneak_attack_spent=None, ally_adjacent=None) -> int:
    weapon = _dagger()
    activity = next(a for a in weapon.activities if a.kind == "attack")
    target = _foe()
    events: list = []
    ctx = _ctx(
        rng=random.Random(9),
        targets=[target],
        event_emitter=events.append,
        active_effects=active_effects,
        sneak_attack_spent=sneak_attack_spent or {},
        sneak_attack_ally_adjacent=ally_adjacent or {},
    )
    resolve_activity(activity, ctx, weapon=weapon)
    return sum(e.amount for e in events if isinstance(e, DamageApplied))


def test_finesse_weapon_without_sneak_dice_gets_no_rider():
    """A non-Rogue swing (no ``rogue.sneak-attack`` scale value) never gets a rider."""
    weapon = _dagger()
    activity = next(a for a in weapon.activities if a.kind == "attack")
    target = _foe()
    base_events: list = []
    ctx = _ctx(
        rng=random.Random(9),
        targets=[target],
        event_emitter=base_events.append,
        scale_values={},
        active_effects=(_flag_effect("flags.advantage.attack"),),
    )
    resolve_activity(activity, ctx, weapon=weapon)
    baseline = sum(e.amount for e in base_events if isinstance(e, DamageApplied))
    # Same seed, with sneak dice present -> a rider is added on top.
    with_rider = _swing_total(active_effects=(_flag_effect("flags.advantage.attack"),))
    assert with_rider - baseline >= 3


def test_once_per_turn_gate_blocks_second_rider():
    baseline = _swing_total()
    unspent = _swing_total(active_effects=(_flag_effect("flags.advantage.attack"),))
    spent = _swing_total(
        active_effects=(_flag_effect("flags.advantage.attack"),),
        sneak_attack_spent={"char:rogue": True},
    )
    assert 3 <= unspent - baseline <= 18
    assert spent - baseline == 0
