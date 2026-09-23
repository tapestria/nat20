"""Task 5 review fix (finding 1) regression — a FIXED ``target.affects.count``
marker (``"1"``, the schema default a plain single-target damage activity
carries: Hex, Hunter's Mark, Wall of Fire, ...) must NOT suppress that
activity's own slot-level dice ``scaling`` (``scaling.mode == "whole"``). Only
a count formula that genuinely references ``@item.level``
(``spellcasting.count_scales_with_cast_level``) — Magic Missile's darts,
Hold Person's extra Humanoids — disables the dice-scaling path in
``resolve_damage`` (R5: the count mechanic wins over the dice mechanic
specifically to avoid double-counting THAT spell's own upcast).

Direct ``activities/damage.py``-level test rather than a live-combat /
``submit_player_intent`` path: Wall of Fire places a wall at a point in
space (its activity's ``target.affects.type == "creature"`` is itself a data
quirk — the count marker, not a real creature target list), so driving it
through the orchestrator's targeting/placement flow would not give a clean,
deterministic assertion. Calling ``resolve_damage`` directly on the real
canonical activity is the accurate, minimal reproduction of the bug.
"""

from __future__ import annotations

import random

from dnd5e_srd_data.loader import BundledAssetLoader

from dnd5e_engine.activities.context import ActivityResolutionContext
from dnd5e_engine.activities.damage import resolve_damage
from dnd5e_engine.events import DamageApplied
from dnd5e_engine.types.combat import Combatant


def _wall_of_fire_damage_activity():
    spell = BundledAssetLoader().get_spell("wall-of-fire")
    assert spell is not None
    activity = next(a for a in spell.activities if a.kind == "damage")
    # Pin the exact data shape this regression guards against misreading:
    # a FIXED single-target marker (not an @item.level formula) alongside a
    # REAL "whole" slot-level dice scaling block.
    assert activity.target.affects.count == "1"
    assert activity.target.affects.type == "creature"
    assert activity.damage.parts[0].scaling.mode == "whole"
    return spell.level, activity


def _cast_total(activity, *, base_level: int, slot_level: int, seed: int) -> int:
    events: list[DamageApplied] = []
    caster = Combatant(
        entity_id="c", entity_type="Character", name="C", initiative=10, hp_current=10, hp_max=10
    )
    target = Combatant(
        entity_id="t", entity_type="Monster", name="T", initiative=1, hp_current=500, hp_max=500
    )
    ctx = ActivityResolutionContext(
        rng=random.Random(seed),
        caster=caster,
        targets=[target],
        event_emitter=events.append,
        caster_abilities={"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10},
        base_spell_level=base_level,
        slot_level=slot_level,
    )
    resolve_damage(activity, ctx)
    return sum(e.amount for e in events)


def test_fixed_count_marker_does_not_suppress_damage_dice_scaling():
    """Before the review fix, ``count_scales_via_targets`` treated ANY non-blank
    creature count — including Wall of Fire's fixed ``"1"`` marker — as an
    upcast-via-count activity, wrongly zeroing ``slot_level`` for the dice roll
    and silently dropping its real +1d8/slot-above-4th upcast. Same RNG seed for
    both calls: the dice evaluator draws each d8 sequentially off the SAME
    stream (``activities/dice.py::_eval_node``), so the upcast roll (7d8) shares
    its first 5 draws with the base roll (5d8) and can only add strictly more —
    a deterministic, not merely probabilistic, inequality.
    """
    base_level, activity = _wall_of_fire_damage_activity()
    base_total = _cast_total(activity, base_level=base_level, slot_level=base_level, seed=7)
    upcast_total = _cast_total(activity, base_level=base_level, slot_level=base_level + 2, seed=7)
    assert upcast_total > base_total
