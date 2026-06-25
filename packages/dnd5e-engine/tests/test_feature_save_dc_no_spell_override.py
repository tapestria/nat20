"""Code-review fix 2 — a FEATURE save activity must not inherit the blanket
spell ``save_dc_override``.

``build_activity_context`` applies a blanket ``save_dc_override`` (the Avrae-era
flat spell DC, ``8 + PB + caster_mod``). A spell-path cast keeps that behavior
(deferred full spellcasting-ability seam). But a USE_FEATURE invocation must NOT
carry the spell override, so a feature's own SaveActivity falls through to the
save resolver's real ability+PB DC computation — correct for ability-keyed
features like ``8 + PB + STR``.

This is a focused unit test on the context-building path: a feature-invocation
context omits ``save_dc_override``; the spell path keeps it.
"""

from __future__ import annotations

import random

from dnd5e_engine.activities.build_context import build_activity_context
from dnd5e_engine.types.combat import Combatant


def _caster() -> Combatant:
    return Combatant(
        entity_id="char:aaaaaaaaaaaa",
        entity_type="Character",
        name="PC",
        initiative=10,
        hp_current=30,
        attack_bonus=5,
        character_level=5,
        strength=18,
        constitution=16,
    )


def _build(*, is_feature_invocation: bool):
    caster = _caster()
    return build_activity_context(
        caster,
        [caster],
        rng=random.Random(1),
        event_emitter=lambda e: None,
        slot_level=1,
        base_spell_level=1,
        spellcasting_ability="int",
        concentration=False,
        source_passive_effects=[],
        spell_book={},
        passive_damage_modifiers={},
        save_modifiers={},
        is_feature_invocation=is_feature_invocation,
    )


def test_spell_context_keeps_blanket_save_dc_override():
    """The spell path is unchanged: the blanket flat DC override is still set."""
    ctx = _build(is_feature_invocation=False)
    assert ctx.save_dc_override is not None


def test_feature_context_omits_save_dc_override():
    """A feature-invocation context does NOT carry the spell override, so a
    feature SaveActivity computes its own DC from real abilities + PB."""
    ctx = _build(is_feature_invocation=True)
    assert ctx.save_dc_override is None
