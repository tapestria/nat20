"""Library-side combat resolver subset of engine_dispatch.

Hosts the pure rules-engine resolvers for the four combat-flavored
action types: ATTACK, CAST_SPELL, SKILL_CHECK, SAVING_THROW. Host
callers (e.g. Tapestria's ``app.rules.engine_dispatch.dispatch_intent``)
keep ownership of the wider intent taxonomy (MOVE, EQUIP_ITEM,
PREPARE_SPELL, QUEST_*, ...) and wrap the lib's ``CombatResolverResult``
into their full ``EngineResult``.

Intent shape — duck-typed
--------------------------
The resolvers accept ``intent: Any`` and read the following attributes:

    action_type, target_id, spell_id, weapon_id, skill_name,
    condition_to_apply

The host's ``app.models.intent.ParsedIntent`` Pydantic model satisfies
the shape. No explicit Protocol is declared because the library never
constructs an intent — it only reads one provided by the host.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from dnd5e_engine.rules.combat import resolve_player_attack
from dnd5e_engine.rules.conditions import check_immunity
from dnd5e_engine.rules.skills import SKILL_ABILITIES
from dnd5e_engine.types.effects import ActiveEffect
from dnd5e_engine.types.intent import (
    ActionType,
    CombatOutcome,
    SavingThrowOutcome,
    SkillOutcome,
)

# ── DispatchContext ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DispatchContext:
    """Pre-fetched context bundle for engine dispatch. Assembled by caller.

    Frozen dataclass: immutable after creation, all data pre-fetched by the
    caller so the engine makes zero DB/LLM calls.
    """

    # Character stats (always needed)
    character_id: str = ""
    ability_scores: dict[str, int] = field(default_factory=dict)
    level: int = 1
    proficiency_bonus: int = 2
    proficient_skills: list[str] = field(default_factory=list)
    expertise_skills: list[str] = field(default_factory=list)
    proficient_saves: list[str] = field(default_factory=list)
    class_slug: str = ""
    weapon_proficiencies: list[str] = field(default_factory=list)

    # Combat context (ATTACK/CAST_SPELL/FLEE)
    target_ac: int = 10
    target_name: str = ""
    target_hp_current: int = 0
    target_hp_max: int = 0
    target_resistances: list[str] = field(default_factory=list)
    target_immunities: list[str] = field(default_factory=list)
    target_save_scores: dict[str, int] = field(default_factory=dict)

    # Weapon data (ATTACK)
    weapon_attack_bonus: int = 0
    weapon_damage_dice: str = "1d1"
    weapon_damage_type: str = "bludgeoning"
    weapon_damage_modifier: int = 0
    weapon_name: str = "Unarmed Strike"

    # Spell data (CAST_SPELL)
    spell_attack_bonus: int = 0
    spell_save_dc: int = 10
    spell_damage_dice: str = "1d4"
    spell_damage_type: str = "force"
    spell_name: str = ""
    spell_is_auto_hit: bool = False
    spell_save_type: str | None = None
    spell_half_on_save: bool = False

    # Movement context (MOVE)
    current_location_id: str = ""
    available_exits: list[dict[str, str]] = field(default_factory=list)
    # Each exit: {"id": "loc:...", "name": "..."}

    # Flee context
    flee_dc: int = 10

    # Condition tracking (Phase 1 v3.1)
    attacker_conditions: list[str] = field(default_factory=list)
    target_conditions: list[str] = field(default_factory=list)
    condition_immunities: dict[str, list[str]] = field(default_factory=dict)
    # entity_id -> list[condition_name] for all combatants in this encounter

    # Equipment state (Phase 2 v3.1)
    equipped_weapon_id: str | None = None  # item ID in right_hand slot (None = unarmed)
    equipped_weapon_name: str = "Unarmed Strike"  # resolved name for narrator
    character_ac: int = 10  # computed AC from armor + dex + shield (D-04)
    armor_type: str = "unarmored"  # light/medium/heavy/unarmored
    non_proficient_armor: bool = False  # True = disadvantage on STR/DEX, no spells (EQUIP-06)
    has_shield: bool = False  # True = shield in left_hand
    in_combat: bool = False  # True when session is in combat phase
    weapon_mismatch: str | None = None  # set when parser picked different weapon than equipped
    shield_item_id: str | None = None  # item ID of shield in left_hand

    # Spell preparation state (Phase 3 v3.1)
    caster_type: str = "none"  # 'prepared' | 'spontaneous' | 'none'
    prep_formula: str = "full"  # 'full' | 'half'
    spellcasting_ability: str = ""  # e.g. 'intelligence', 'wisdom'
    prepared_spell_ids: frozenset[str] = field(default_factory=frozenset)
    # spell_id -> level (0=cantrip)
    known_spell_levels: dict[str, int] = field(default_factory=dict)
    # Spell slot availability, indexed by (spell_level - 1). E.g. a 5th-level
    # wizard with 4/4/3 slots has available_spell_slots == (4, 4, 3). Empty
    # tuple = no slot data loaded (non-caster or context built outside combat).
    # Post-refactor (Root Cause B fix): dispatch is the authoritative gate for
    # spell-slot availability. Prior implementation checked slot count only
    # at ws_player_action.py with a silent `> 0` fallback that let
    # zero-slot casts resolve anyway. Engine_dispatch rejects before resolver
    # runs when the relevant slot bucket is empty.
    available_spell_slots: tuple[int, ...] = field(default_factory=tuple)

    # Persistent effects (Phase 4 v3.1) — fetched from Redis in build_dispatch_context
    # active_effects: effects on the attacker (modify attack rolls, the attacker's own saves)
    # target_active_effects: effects on the target (modify the target's saving throws when the
    # attacker forces a save, e.g. Bless on the defender adding +1d4 to their Dex save vs Fireball)
    active_effects: tuple[ActiveEffect, ...] = field(default_factory=tuple)
    target_active_effects: tuple[ActiveEffect, ...] = field(default_factory=tuple)


# ── CombatResolverResult ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class CombatResolverResult:
    """Result fragment from the library's combat-action resolvers.

    Host's ``app.rules.engine_dispatch.dispatch_intent`` wraps this into
    ``app.models.intent.EngineResult`` by attaching ``action_type`` plus
    the host-only sub-outcomes (MovementOutcome, EquipOutcome,
    PrepareOutcome) which the library never populates.
    """

    resolved: bool = True
    combat: CombatOutcome | None = None
    skill_check: SkillOutcome | None = None
    saving_throw: SavingThrowOutcome | None = None
    dodge_active: bool = False
    error: str | None = None
    immunity_blocked: bool = False
    immunity_blocked_condition: str | None = None
    immunity_blocked_target: str | None = None


# ── Resolvers ────────────────────────────────────────────────────────────────


def _resolve_combat(intent: Any, ctx: DispatchContext) -> CombatResolverResult:
    """Resolve ATTACK or CAST_SPELL via rules engine."""
    # D-11: Block spellcasting while wearing non-proficient armor (EQUIP-06)
    if intent.action_type == ActionType.CAST_SPELL and ctx.non_proficient_armor:
        return CombatResolverResult(
            resolved=False,
            error="Cannot cast spells while wearing non-proficient armor",
        )

    # Check condition immunity before resolving (COND-04)
    # condition_to_apply is set by the LLM parser when the action attempts to apply a condition.
    condition_to_apply = intent.condition_to_apply
    if condition_to_apply:
        target_id = intent.target_id or ""
        target_immunity_list = ctx.condition_immunities.get(target_id, [])
        if check_immunity(condition_to_apply, target_immunity_list):
            # Resolve combat for damage but flag immunity block
            if intent.action_type == ActionType.ATTACK:
                combat_result = resolve_player_attack(
                    action_type="attack",
                    attack_bonus=ctx.weapon_attack_bonus,
                    target_ac=ctx.target_ac,
                    damage_dice=ctx.weapon_damage_dice,
                    damage_type=ctx.weapon_damage_type,
                    damage_modifier=ctx.weapon_damage_modifier,
                    target_name=ctx.target_name,
                    target_hp_current=ctx.target_hp_current,
                    target_hp_max=ctx.target_hp_max,
                    target_resistances=ctx.target_resistances or None,
                    target_immunities=ctx.target_immunities or None,
                    attacker_conditions=list(ctx.attacker_conditions),
                    target_conditions=list(ctx.target_conditions),
                    active_effects=ctx.active_effects,
                    target_active_effects=ctx.target_active_effects,
                )
            else:
                target_save_score = ctx.target_save_scores.get(ctx.spell_save_type or "", 10)
                combat_result = resolve_player_attack(
                    action_type="cast_spell",
                    attack_bonus=ctx.spell_attack_bonus,
                    target_ac=ctx.target_ac,
                    damage_dice=ctx.spell_damage_dice,
                    damage_type=ctx.spell_damage_type,
                    damage_modifier=0,
                    target_name=ctx.target_name,
                    target_hp_current=ctx.target_hp_current,
                    target_hp_max=ctx.target_hp_max,
                    target_resistances=ctx.target_resistances or None,
                    target_immunities=ctx.target_immunities or None,
                    is_auto_hit=ctx.spell_is_auto_hit,
                    save_type=ctx.spell_save_type,
                    save_dc=ctx.spell_save_dc,
                    target_save_score=target_save_score,
                    half_on_save=ctx.spell_half_on_save,
                    attacker_conditions=list(ctx.attacker_conditions),
                    target_conditions=list(ctx.target_conditions),
                    active_effects=ctx.active_effects,
                    target_active_effects=ctx.target_active_effects,
                )
            return CombatResolverResult(
                resolved=True,
                immunity_blocked=True,
                immunity_blocked_condition=condition_to_apply,
                immunity_blocked_target=ctx.target_name,
                combat=combat_result,
            )

    if intent.action_type == ActionType.ATTACK:
        result = resolve_player_attack(
            action_type="attack",
            attack_bonus=ctx.weapon_attack_bonus,
            target_ac=ctx.target_ac,
            damage_dice=ctx.weapon_damage_dice,
            damage_type=ctx.weapon_damage_type,
            damage_modifier=ctx.weapon_damage_modifier,
            target_name=ctx.target_name,
            target_hp_current=ctx.target_hp_current,
            target_hp_max=ctx.target_hp_max,
            target_resistances=ctx.target_resistances or None,
            target_immunities=ctx.target_immunities or None,
            attacker_conditions=list(ctx.attacker_conditions),
            target_conditions=list(ctx.target_conditions),
            active_effects=ctx.active_effects,
            target_active_effects=ctx.target_active_effects,
        )
    else:  # CAST_SPELL
        target_save_score = ctx.target_save_scores.get(ctx.spell_save_type or "", 10)
        result = resolve_player_attack(
            action_type="cast_spell",
            attack_bonus=ctx.spell_attack_bonus,
            target_ac=ctx.target_ac,
            damage_dice=ctx.spell_damage_dice,
            damage_type=ctx.spell_damage_type,
            damage_modifier=0,
            target_name=ctx.target_name,
            target_hp_current=ctx.target_hp_current,
            target_hp_max=ctx.target_hp_max,
            target_resistances=ctx.target_resistances or None,
            target_immunities=ctx.target_immunities or None,
            is_auto_hit=ctx.spell_is_auto_hit,
            save_type=ctx.spell_save_type,
            save_dc=ctx.spell_save_dc,
            target_save_score=target_save_score,
            half_on_save=ctx.spell_half_on_save,
            attacker_conditions=list(ctx.attacker_conditions),
            target_conditions=list(ctx.target_conditions),
            active_effects=ctx.active_effects,
            target_active_effects=ctx.target_active_effects,
        )

    return CombatResolverResult(
        resolved=True,
        combat=result,
    )


def _resolve_skill_check(intent: Any, ctx: DispatchContext) -> CombatResolverResult:
    """Resolve SKILL_CHECK via resolve_check (Phase 5).

    Threads `ctx.active_effects` through the resolver so Bless / Guidance
    land on SKILL_CHECK dispatch. EQUIP-06 non-proficient-armor
    disadvantage on STR/DEX skills is expressed via `spec.disadvantage`.
    """
    from dnd5e_engine.check import CheckSpec, resolve_check

    skill_name = intent.skill_name or "perception"

    # Task difficulty is the parser's judgment call (it sees the action text and
    # situation). Thread it into the CheckSpec so the roll resolves to a real
    # Success/Failure; fall back to medium (DC 15) when the parser supplied none.
    check_dc = getattr(intent, "check_dc", None)
    if check_dc is None:
        check_dc = 15

    # EQUIP-06: non-proficient armor imposes disadvantage on STR/DEX skill
    # checks. Determined here (host-domain rule) and threaded through the
    # CheckSpec rather than re-derived inside the resolver.
    non_prof_disadvantage = False
    if ctx.non_proficient_armor:
        normalized_skill = skill_name.lower().replace(" ", "_")
        skill_ability = SKILL_ABILITIES.get(normalized_skill, "intelligence")
        if skill_ability in ("strength", "dexterity"):
            non_prof_disadvantage = True

    result = resolve_check(
        CheckSpec(
            kind="skill",
            skill=skill_name,
            ability_scores=ctx.ability_scores,
            proficient_skills=tuple(ctx.proficient_skills),
            proficient_saves=tuple(ctx.proficient_saves),
            proficiency_bonus=ctx.proficiency_bonus,
            expertise_skills=tuple(ctx.expertise_skills),
            dc=check_dc,
            disadvantage=non_prof_disadvantage,
            active_effects=ctx.active_effects,
        )
    )

    return CombatResolverResult(
        resolved=True,
        skill_check=SkillOutcome(
            skill=result.skill,
            ability=result.ability,
            roll_total=result.roll_total,
            modifier=result.modifier,
            dc=result.dc,
            success=result.success,
            natural_roll=result.natural_roll,
        ),
    )


def resolve_combat_action(intent: Any, ctx: DispatchContext) -> CombatResolverResult:
    """Resolve ATTACK / CAST_SPELL / SKILL_CHECK.

    Intent is duck-typed: see module docstring for the attribute contract.
    SAVING_THROW is reserved in the ActionType taxonomy but has no dispatch
    branch today (the parser does not emit it). When the host wires it,
    extend this dispatcher rather than re-introducing per-branch hooks.
    """
    if intent.action_type == ActionType.SKILL_CHECK:
        return _resolve_skill_check(intent, ctx)
    # ATTACK or CAST_SPELL
    return _resolve_combat(intent, ctx)


__all__ = [
    "CombatResolverResult",
    "DispatchContext",
    "resolve_combat_action",
]
