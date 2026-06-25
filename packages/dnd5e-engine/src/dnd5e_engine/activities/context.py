from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from dnd5e_engine.events import CombatEvent
from dnd5e_engine.types.combat import Combatant

if TYPE_CHECKING:
    from dnd5e_srd_data.schema.common import PassiveEffect
    from dnd5e_srd_data.schema.spell import Spell


@dataclass(frozen=True)
class ActivityResolutionContext:
    """Caster/target state + seeded RNG + event sink for one activity resolution.

    Built directly by golden-corpus tests in Piece 1; built by the orchestrator
    from live combat state in Piece 3. Caster-derived magnitudes (ability mods,
    proficiency, spellcasting ability) live here because the typed Activity only
    declares WHICH ability/DC-calc to use, not the caster's numbers.
    """

    rng: random.Random
    caster: Combatant
    targets: list[Combatant]
    event_emitter: Callable[[CombatEvent], None]
    caster_abilities: dict[str, int]  # {"str":..,"dex":..,...} six scores
    caster_proficiency_bonus: int = 2
    # Caster's total character level, drives cantrip damage scaling (SRD §Cantrips:
    # 1 die ≤4, 2 dice 5–10, 3 dice 11–16, 4 dice 17+). Only consulted for cantrips
    # (``base_spell_level == 0``); inert for leveled spells and weapon attacks.
    caster_level: int = 1
    spellcasting_ability: str | None = None  # for save.dc.calculation == "spellcasting"
    is_proficient_attack: bool = True
    # The casting spell's concentration flag (``Spell.concentration``). Threaded
    # into each rider ``ActiveEffect.flags`` as ``{"concentration": True}`` so the
    # orchestrator (Piece 3) can key concentration-drop + repeat-save lineage off
    # it. Supplied by golden fixtures now; threaded by the orchestrator (from the
    # spell's typed ``concentration``) at cutover. Inert for non-spell activities.
    concentration: bool = False
    slot_level: int | None = None
    # The spell's BASE level (lowest castable slot). Upcast scaling adds
    # ``max(0, slot_level - base_spell_level)`` steps. Supplied by golden
    # fixtures now; by the orchestrator (from the spell's typed level) at
    # cutover. ``None`` disables upcast scaling (a non-spell activity).
    base_spell_level: int | None = None
    # Fixed save DC from a cast wrapper's challenge override (Foundry
    # `spell.challenge.override` + `save`): when set, the save handler uses this
    # verbatim DC instead of the spellcasting/flat calculation. Set by resolve_cast
    # from the item's fixed challenge; None for normal (caster-stat) casting.
    save_dc_override: int | None = None
    # Fixed attack bonus from a cast wrapper's challenge override
    # (`spell.challenge.override` + `attack`): when set, the attack handler uses
    # this verbatim to-hit instead of ability + proficiency + weapon. None otherwise.
    attack_bonus_override: int | None = None
    # Player-supplied damage-type choice per activity id, for parts that offer a
    # CHOICE of damage type (``DamagePartBlock.types`` with >1 entry — e.g.
    # Chromatic Orb's [acid, cold, fire, ...]). Keyed by activity id; the chosen
    # value must be one of the part's listed types. Absent → the first listed
    # type is used (logged at INFO). Supplied by player intent at cutover.
    damage_type_choices: dict[str, str] = field(default_factory=dict)
    # Reuse the engine's EXISTING passive-damage sidecar shape
    # (entity_id -> {"resistances","immunities","vulnerabilities"}), mirroring
    # effects/damage.py `_read_passive_modifiers`. Do NOT invent a separate
    # target_vulnerabilities carrier.
    passive_damage_modifiers: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    # Per-target saving-throw modifier sidecar, keyed entity_id -> {ability ->
    # resolved save bonus}. Mirrors how ``effects/save.py`` sources the target
    # save modifier (``effect_store._save_modifiers[target_id]["saves"][ability]``)
    # — the resolved per-ability integer, NOT rebuilt from ability score +
    # proficiency. ``Combatant`` carries no per-ability save table, so the save
    # handler reads this sidecar; an absent target / ability contributes +0
    # (mirrors ``_read_save_modifier``'s 0 fallback). Supplied by the orchestrator
    # (from target stat blocks) at cutover; by golden fixtures now.
    passive_save_modifiers: dict[str, dict[str, int]] = field(default_factory=dict)
    # Per-target additive save bonus, keyed entity_id -> a signed dice-expression
    # STRING (e.g. ``"+1d4"`` for Bless, ``"-1d4"`` for Bane; stacked sources
    # pre-joined as ``"a + b"``). Mirrors the OLD Avrae path's
    # ``effect_store._save_modifiers[id]["passive_save_bonus"]`` (orchestrator
    # hydration, ``_build_hydration_payload``); rolled through ``ctx.rng`` so the
    # bless/bane d4 lands in the same seed stream as the save d20. Absent target →
    # +0 (no bonus). Empty default keeps the golden corpus identical.
    passive_save_bonus: dict[str, str] = field(default_factory=dict)
    # Per-ATTACKER additive to-hit bonus, keyed entity_id -> a signed
    # dice-expression STRING (``"+1d4"`` Bless, ``"-1d4"`` Bane; stacked sources
    # pre-joined). The attacker-side analogue of ``passive_save_bonus``: SRD §Bane
    # /§Bless apply the d4 to the affected creature's own attack rolls, so this is
    # keyed on the attacker (``ctx.caster``), not the target. Sourced from the
    # orchestrator's ``passive_damage_modifiers[id]["passive_to_hit_bonus"]``
    # projection; rolled through ``ctx.rng`` so the d4 lands in the same seed
    # stream as the attack d20. Absent → +0. Empty default keeps the golden
    # corpus identical.
    passive_attack_bonus: dict[str, str] = field(default_factory=dict)
    # Per-ATTACKER additive MELEE-WEAPON damage bonus, keyed entity_id -> a signed
    # numeric/dice STRING (Rage's ``+2`` at L5; stacked sources pre-joined). The
    # melee-damage analogue of ``passive_attack_bonus``: Foundry's
    # ``system.bonuses.mwak.damage`` (melee weapon attack damage) buffs the
    # attacker's MELEE weapon damage only — NOT ranged or spell. Folded from the
    # caster's active effects in the orchestrator's ``_build_hydration_payload``
    # and consumed in ``attack.py:_apply_on_hit_damage`` gated to a melee weapon.
    # Absent attacker → +0. Empty default keeps the golden corpus identical.
    passive_melee_damage_bonus: dict[str, str] = field(default_factory=dict)
    # Per-target save-advantage / -disadvantage ability-code lists (UPPER-case:
    # ``"STR"``, ``"DEX"``, ...), keyed entity_id -> list[ability]. Mirrors the
    # OLD path's ``passive_save_adv`` / ``passive_save_dis`` (Faerie Fire,
    # Restrained, etc.). An ability present in both cancels to normal
    # (Avrae ``reconcile_adv``). Empty defaults keep the golden corpus identical.
    passive_save_adv: dict[str, list[str]] = field(default_factory=dict)
    passive_save_dis: dict[str, list[str]] = field(default_factory=dict)
    # Per-target auto-fail ability-code list (UPPER-case), keyed entity_id ->
    # list[ability]. SRD §Conditions: Paralyzed / Stunned / Petrified /
    # Unconscious creatures auto-fail STR + DEX saves; Restrained does not. When
    # the rolled ability is listed the save short-circuits to failure with NO d20
    # draw (matching ``effects/save.py`` + ``conditions.py`` semantics), so the
    # deterministic rng stream is not perturbed. Empty default = no auto-fail.
    passive_save_auto_fail: dict[str, list[str]] = field(default_factory=dict)
    # Per-actor ability/skill-check modifier sidecar, mirroring
    # ``effects/check.py:_read_check_modifiers``'s shape
    # ``{entity_id: {"skills": {code: mod}, "ability_mods": {ability: mod}}}``.
    # The RESOLVED per-skill / per-ability integer, NOT rebuilt from ability
    # score + proficiency. ``Combatant`` carries no per-skill table, so the
    # ``check`` handler reads this sidecar; an absent actor / skill / ability
    # contributes +0. Supplied by golden fixtures now; by the orchestrator (from
    # actor stat blocks) at cutover.
    check_modifiers: dict[str, dict[str, dict[str, int]]] = field(default_factory=dict)
    # Effect definitions riding the activity's applied-effect refs, to be
    # translated into runtime ``ActiveEffect``s (one per target) via
    # ``activities/effects.passive_effect_to_active_effect``. Supplied by golden
    # fixtures now; by the orchestrator (resolving ``activity.effects[].id`` →
    # the spell's typed ``passive_effects``) at cutover.
    source_passive_effects: list[PassiveEffect] = field(default_factory=list)
    # Spell lookup table for `cast` delegation, keyed by Foundry spell uuid →
    # the typed Spell. A `cast` activity resolves `spell.uuid` here, then
    # re-enters resolve_activity for each of the referenced spell's activities.
    # Supplied by golden fixtures now; by the orchestrator (from the caster's
    # known spells) at cutover.
    spell_book: dict[str, Spell] = field(default_factory=dict)
    # Recursion guard for `cast`: the chain of spell uuids already being cast
    # this resolution. A uuid already present means a spell-within-itself cycle —
    # the cast handler logs and no-ops rather than recursing infinitely.
    parent_chain: tuple[str, ...] = ()
    # Pre-resolved ScaleValue magnitudes for the caster's class/subclass/species,
    # keyed by the full dotted ``@scale.*`` token suffix
    # (``"barbarian.rage-damage"`` -> 2, ``"rogue.sneak-attack"`` -> ``"3d6"``,
    # ``"rogue.sneak-attack.number"`` -> 3). Int for number/distance scales and
    # dice ``.number`` counts; dice-expr STRING for bare/``.die`` dice scales.
    # Resolved at the orchestrator/build-party seam (loader access there) by
    # ``activities/scale.build_scale_values`` and passed in as plain data — the
    # ``@scale.*`` formula branch never touches a loader (purity). Empty default
    # keeps the golden corpus identical.
    scale_values: dict[str, int | str] = field(default_factory=dict)
    # Pre-resolved class levels keyed by class slug (``{"fighter": 5}``) for the
    # ``@classes.<class>.levels`` token (Second Wind's HP heal scales by Fighter
    # level). Resolved at the same seam from the caster's class/level. Empty
    # default keeps the golden corpus identical.
    class_levels: dict[str, int] = field(default_factory=dict)
    # Test-determinism seams (our own code): variables["force_d20"],
    # variables["force_save_d20"], variables["in_crit"].
    variables: dict[str, int] = field(default_factory=dict)

    def ability_mod(self, ability: str) -> int:
        return (self.caster_abilities.get(ability, 10) - 10) // 2
