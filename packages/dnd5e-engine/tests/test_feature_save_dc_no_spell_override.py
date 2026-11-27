"""A FEATURE or ITEM save activity must not inherit the blanket spell
``save_dc_override``.

``build_activity_context`` applies a blanket ``save_dc_override`` (the Avrae-era
flat spell DC, ``8 + PB + caster_mod``). A spell-path cast keeps that behavior
(deferred full spellcasting-ability seam). But a USE_FEATURE invocation must NOT
carry the spell override, so a feature's own SaveActivity falls through to the
save resolver's real ability+PB DC computation — correct for ability-keyed
features like ``8 + PB + STR``.

This is a focused unit test on the context-building path: a context whose
activities state their own DC omits ``save_dc_override`` yet keeps the caster's
spell DC on ``spell_save_dc`` (for an item's delegated cast); the spell path
keeps the override.
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


def _build(*, activities_state_own_dc: bool):
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
        activities_state_own_dc=activities_state_own_dc,
    )


def test_spell_context_keeps_blanket_save_dc_override():
    """The spell path is unchanged: the blanket flat DC override is still set."""
    ctx = _build(activities_state_own_dc=False)
    assert ctx.save_dc_override is not None


def test_feature_context_omits_save_dc_override():
    """A feature-invocation context does NOT carry the spell override, so a
    feature SaveActivity computes its own DC from real abilities + PB."""
    ctx = _build(activities_state_own_dc=True)
    assert ctx.save_dc_override is None


def test_own_dc_context_keeps_the_spell_dc_for_a_delegated_cast():
    """The caster's spell DC still rides on ``spell_save_dc``, equal to the
    blanket a spell's own resolution gets."""
    own = _build(activities_state_own_dc=True)
    spell = _build(activities_state_own_dc=False)
    assert own.spell_save_dc == spell.save_dc_override == spell.spell_save_dc
    assert own.spell_save_dc is not None
