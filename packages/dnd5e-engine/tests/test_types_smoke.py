"""Smoke test — types are importable and instantiate cleanly.

Phase 6 migration: ``EffectModifier`` → ``ActiveEffectChange``; ``ActiveEffect``
now carries ``id``/``name``/``origin``/``target_id`` + ``changes`` + ``duration``.
``EffectRef`` is retired (Redis-resident hydration shape is gone).
"""

from __future__ import annotations


def test_active_condition_round_trip():
    from dnd5e_engine.types.conditions import ActiveCondition, ConditionScope

    scope: ConditionScope = "combat"
    ac = ActiveCondition(
        condition="poisoned",
        source_entity_id="effect:abc123def456",
        scope=scope,
    )
    assert ac.scope == "combat"
    assert ac.condition == "poisoned"


def test_dice_outcome_round_trip():
    from dnd5e_engine.types.dice import DiceOutcome

    do = DiceOutcome(
        request_id="r1",
        character_id="c1",
        roll_type="attack",
        roll_total=18,
        natural_roll=14,
        modifier=4,
        dice=[14],
        dc=15,
        success=True,
        summary="Attack: 18 vs AC 15",
    )
    assert do.roll_total == 18
    assert do.is_critical is False


def test_combatant_round_trip():
    from dnd5e_engine.types.combat import Combatant

    c = Combatant(
        entity_id="char:abc123def456",
        entity_type="Character",
        name="Aric",
        initiative=14,
        hp_current=12,
        hp_max=12,
    )
    assert c.hp_current == 12
    assert c.is_alive is True


def test_combat_npc_round_trip():
    from dnd5e_engine.types.combat import CombatNPC

    c = CombatNPC(
        npc_id="npc:abc123def456",
        template_id="mt:bandit",
        name="Bandit",
        hp_current=11,
        hp_max=11,
        ac=12,
        attack_bonus=3,
        damage_dice="1d6+1",
        damage_type="slashing",
    )
    assert c.hp_current == 11


def test_action_type_string_values():
    from dnd5e_engine.types.intent import ActionType

    assert ActionType.ATTACK.value == "attack"
    assert ActionType("cast_spell") == ActionType.CAST_SPELL


def test_action_type_case_insensitive_lookup():
    """Library-owned _missing_ provides case-insensitive construction."""
    from dnd5e_engine.types.intent import ActionType

    assert ActionType("EXAMINE_LOCATION") == ActionType.EXAMINE_LOCATION
    assert ActionType("Quest_Resolution_Attempt") is ActionType.QUEST_RESOLUTION_ATTEMPT
    assert ActionType("CONSULT_CODEX") is ActionType.CONSULT_CODEX


def test_active_effect_change_round_trip():
    from dnd5e_engine.types.effects import ActiveEffectChange

    c = ActiveEffectChange(
        key="attack.roll.bonus", mode="add", value=2, priority=20
    )
    assert c.value == 2
    assert c.key == "attack.roll.bonus"
    assert c.mode == "add"


def test_active_effect_round_trip():
    from dnd5e_engine.types.effects import (
        ActiveEffect,
        ActiveEffectChange,
        ActiveEffectDuration,
    )

    eff = ActiveEffect(
        id="fx:abc123def456",
        name="+1 Weapon",
        origin="item:weapon_plus_one:1",
        target_id="char:abc123def456",
        duration=ActiveEffectDuration(rounds=10),
        changes=[
            ActiveEffectChange(
                key="attack.roll.bonus", mode="add", value=1, priority=20
            ),
            ActiveEffectChange(
                key="damage.bonus", mode="add", value="1d4", priority=20
            ),
        ],
    )
    assert eff.duration.rounds == 10
    assert len(eff.changes) == 2


def test_active_effect_default_permanent_duration():
    """Item effects use the default duration (no round budget)."""
    from dnd5e_engine.types.effects import ActiveEffect, ActiveEffectChange

    eff = ActiveEffect(
        id="fx:permabuff0001",
        name="Ring of Protection",
        origin="item:ring_of_protection:1",
        target_id="char:abc123def456",
        changes=[
            ActiveEffectChange(key="ac.bonus", mode="add", value=1, priority=20),
        ],
    )
    assert eff.duration.rounds is None


def test_combat_outcome_round_trip():
    from dnd5e_engine.types.intent import CombatOutcome

    co = CombatOutcome(
        hit=True,
        damage_dealt=8,
        damage_type="slashing",
        attack_roll=17,
        target_ac=14,
        is_critical=False,
        target_name="Bandit",
        target_hp_remaining=3,
        target_hp_max=11,
        target_died=False,
    )
    assert co.hit is True
    assert co.target_died is False
