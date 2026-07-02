"""C02-S01 — a weapon-tagged ``damage.bonus`` active effect reaches the
swing's damage, not just its to-hit.

``orchestrator._fold_active_effect_changes`` already folds a weapon-tagged
``damage.bonus`` change into the ``passive_weapon_damage_bonus`` sidecar key
(``per_target_dmg``), but nothing downstream ever read it:
``build_context.py::build_activity_context`` didn't lift it into a typed
``ActivityResolutionContext`` field, and ``attack.py::_apply_on_hit_damage``
never consulted one. This is a focused unit test on the consumption seam
(mirrors the ``passive_melee_damage_bonus`` precedent in
``tests/e2e/test_c07_sneak_and_repertoire.py``'s direct-resolver pattern);
the full write-to-swing path is covered end to end by
``tests/e2e/test_c02_small_mechanics.py::test_c02_s01_...``.
"""

from __future__ import annotations

import random

from dnd5e_srd_data.loader import BundledAssetLoader

from dnd5e_engine.activities.context import ActivityResolutionContext
from dnd5e_engine.activities.resolver import resolve_activity
from dnd5e_engine.events import DamageApplied
from dnd5e_engine.types.combat import Combatant


def _hit_total(passive_weapon_damage_bonus: dict[str, str]) -> int:
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
        ac=1,
    )
    events: list = []
    ctx = ActivityResolutionContext(
        rng=random.Random(11),
        caster=attacker,
        targets=[target],
        event_emitter=events.append,
        caster_abilities={"str": 16, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10},
        caster_proficiency_bonus=2,
        caster_level=1,
        passive_weapon_damage_bonus=passive_weapon_damage_bonus,  # type: ignore[call-arg]
    )
    resolve_activity(activity, ctx, weapon=longsword)
    return sum(e.amount for e in events if isinstance(e, DamageApplied))


def test_weapon_damage_bonus_sidecar_adds_flat_bonus_to_swing_damage():
    base_total = _hit_total({})
    buffed_total = _hit_total({"char:hero": "+3"})
    assert buffed_total == base_total + 3


def test_weapon_damage_bonus_sidecar_absent_attacker_contributes_zero():
    # Absent attacker key -> +0, matching the empty-sidecar convention every
    # other passive_* dict follows (keeps the golden corpus identical).
    assert _hit_total({}) == _hit_total({"mon:someone_else": "+5"})
