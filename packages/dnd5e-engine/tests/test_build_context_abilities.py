"""Task 1 (phase 7c) — ``build_activity_context`` reads real PC abilities + PB.

Piece 3 landed real per-ability scores + ``character_level`` on ``Combatant``.
For PC casters (``entity_type == "Character"``) the context must now expose the
real ability mods and a level-derived proficiency bonus, instead of the
Avrae-era uniform fake (``10 + 2*mod`` from ``attack_bonus``, ``PB == 2``).
Monsters keep the ``attack_bonus``-derived uniform path.
"""

from __future__ import annotations

import random

from dnd5e_engine.activities.build_context import build_activity_context
from dnd5e_engine.types.combat import Combatant


def _build(caster: Combatant, targets: list[Combatant], **kw):
    params: dict = dict(
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
    )
    params.update(kw)
    return build_activity_context(caster, targets, **params)


def test_pc_context_uses_real_abilities_and_level_pb():
    caster = Combatant(
        entity_id="char:aaaaaaaaaaaa",
        entity_type="Character",
        name="PC",
        initiative=10,
        hp_current=30,
        attack_bonus=5,
        character_level=5,  # PB +3 (2 + (5-1)//4)
        strength=18,  # mod +4
        dexterity=12,
        constitution=14,
        intelligence=8,
        wisdom=13,
        charisma=10,
    )
    ctx = _build(caster, [caster])
    assert ctx.ability_mod("str") == 4
    assert ctx.ability_mod("dex") == 1
    assert ctx.ability_mod("int") == -1
    assert ctx.caster_proficiency_bonus == 3


def test_monster_caster_keeps_attack_bonus_derived_path():
    # Monster: mod = attack_bonus (uniform), PB = 2 — unchanged.
    monster = Combatant(
        entity_id="mon:bbbbbbbbbbbb",
        entity_type="Monster",
        name="Cultist",
        initiative=8,
        hp_current=15,
        attack_bonus=4,
        character_level=1,
        strength=18,  # ignored: monster path is attack_bonus-derived
    )
    ctx = _build(monster, [monster])
    assert ctx.caster_proficiency_bonus == 2
    for ability in ("str", "dex", "con", "int", "wis", "cha"):
        assert ctx.ability_mod(ability) == 4
