from __future__ import annotations

import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from dnd5e_engine.events import CombatEvent
from dnd5e_engine.types.combat import Combatant

if TYPE_CHECKING:
    from dnd5e_srd_data.schema.common import PassiveEffect
    from dnd5e_srd_data.schema.spell import Spell

    from dnd5e_engine.types.effects import ActiveEffect


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
    # Cast level forced by a variable-charge item invocation (wand upcast):
    # ``base activity level + extra charges``. When set, resolve_cast uses it
    # verbatim (bounds-checked) instead of the activity/spell level. None for
    # every non-item cast.
    cast_level_override: int | None = None
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
    # save modifier (``the host effect store._save_modifiers[target_id]["saves"][ability]``)
    # — the resolved per-ability integer, NOT rebuilt from ability score +
    # proficiency. ``Combatant`` carries no per-ability save table, so the save
    # handler reads this sidecar; an absent target / ability contributes +0
    # (mirrors ``_read_save_modifier``'s 0 fallback). Supplied by the orchestrator
    # (from target stat blocks) at cutover; by golden fixtures now.
    passive_save_modifiers: dict[str, dict[str, int]] = field(default_factory=dict)
    # Per-target additive save bonus, keyed entity_id -> a signed dice-expression
    # STRING (e.g. ``"+1d4"`` for Bless, ``"-1d4"`` for Bane; stacked sources
    # pre-joined as ``"a + b"``). Mirrors the OLD the legacy evaluator path's
    # ``the host effect store._save_modifiers[id]["passive_save_bonus"]`` (orchestrator
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
    # Per-ATTACKER additive WEAPON damage bonus, keyed entity_id -> a signed
    # numeric/dice STRING (a +N weapon / weapon-tagged buff's ``damage.bonus``
    # change; stacked sources pre-joined). SRD §Making an Attack / §Magic
    # Items: a magic weapon's bonus applies to BOTH the attack roll and the
    # damage roll made with it. Applies to ANY weapon swing (melee or ranged) —
    # unlike ``passive_melee_damage_bonus`` (Rage), which is melee-only.
    # Sourced from the orchestrator's action-type-tagged
    # ``passive_damage_modifiers[id]["passive_weapon_damage_bonus"]``
    # projection (``_fold_active_effect_changes``'s ``weapon_only`` branch);
    # consumed in ``attack.py:_apply_on_hit_damage`` gated on a weapon being
    # present. Absent attacker → +0. Empty default keeps the golden corpus
    # identical.
    passive_weapon_damage_bonus: dict[str, str] = field(default_factory=dict)
    # Per-ATTACKER additive RANGED-WEAPON damage bonus, keyed entity_id -> a
    # signed numeric/dice STRING. Foundry's ``system.bonuses.rwak.damage``
    # (ranged weapon attack damage) — the ranged analog of
    # ``passive_melee_damage_bonus`` (Rage's melee-only ``mwak.damage``).
    # Folded from the caster's active effects in the orchestrator's
    # ``_build_hydration_payload`` and consumed in
    # ``attack.py:_apply_on_hit_damage`` gated to a ranged weapon. Absent
    # attacker -> +0. Empty default keeps the golden corpus identical.
    passive_ranged_damage_bonus: dict[str, str] = field(default_factory=dict)
    # Per-ATTACKER additive MELEE-SPELL-ATTACK damage bonus, keyed entity_id ->
    # a signed numeric/dice STRING. Foundry's ``system.bonuses.msak.damage``
    # (melee spell attack damage — e.g. Shocking Grasp). Consumed in
    # ``attack.py`` gated on a no-weapon melee-classified attack activity.
    # Absent attacker -> +0.
    passive_melee_spell_damage_bonus: dict[str, str] = field(default_factory=dict)
    # Per-ATTACKER additive RANGED-SPELL-ATTACK damage bonus, keyed entity_id ->
    # a signed numeric/dice STRING. Foundry's ``system.bonuses.rsak.damage``
    # (ranged spell attack damage — e.g. Fire Bolt). Consumed in ``attack.py``
    # gated on a no-weapon ranged-classified attack activity. Absent
    # attacker -> +0.
    passive_ranged_spell_damage_bonus: dict[str, str] = field(default_factory=dict)
    # Per-target save-advantage / -disadvantage ability-code lists (UPPER-case:
    # ``"STR"``, ``"DEX"``, ...), keyed entity_id -> list[ability]. Mirrors the
    # OLD path's ``passive_save_adv`` / ``passive_save_dis`` (Faerie Fire,
    # Restrained, etc.). An ability present in both cancels to normal
    # (the legacy evaluator ``reconcile_adv``). Empty defaults keep the golden corpus identical.
    passive_save_adv: dict[str, list[str]] = field(default_factory=dict)
    passive_save_dis: dict[str, list[str]] = field(default_factory=dict)
    # Per-target auto-fail ability-code list (UPPER-case), keyed entity_id ->
    # list[ability]. SRD §Conditions: Paralyzed / Stunned / Petrified /
    # Unconscious creatures auto-fail STR + DEX saves; Restrained does not. When
    # the rolled ability is listed the save short-circuits to failure with NO d20
    # draw (matching ``effects/save.py`` + ``conditions.py`` semantics), so the
    # deterministic rng stream is not perturbed. Empty default = no auto-fail.
    passive_save_auto_fail: dict[str, list[str]] = field(default_factory=dict)
    # Per-TARGET SRD 5.2 §Cover degree ("none"/"half"/"three_quarters"/
    # "total"), keyed entity_id -> degree. Computed once per activity
    # resolution by the orchestrator (``_target_cover_map``) from the
    # caster's and target's live zone via ``SpatialTopology.cover_between``.
    # Consumed in ``attack.py`` (folds +2/+5 onto the target's AC before the
    # hit comparison) and ``save.py``/``save_primitive.py`` (folds the SAME
    # +2/+5 onto a DEXTERITY save's total only — SRD: cover grants "a bonus
    # to AC and Dexterity saving throws"). Absent target -> "none" (+0).
    # Empty default keeps the golden corpus identical (no cover geometry).
    target_cover: dict[str, str] = field(default_factory=dict)
    # C16b — SRD 5.2 "Unseen Attackers and Targets". Per-target visibility
    # projected by the orchestrator (``_target_visibility_maps`` via
    # ``SpatialTopology.can_see`` + ``Combatant.senses``). ``target_unseen[id]``
    # True ⇒ the attacker cannot see that target ⇒ ``"unseen"`` disadvantage;
    # ``attacker_unseen_by[id]`` True ⇒ that target cannot see the attacker ⇒
    # ``"unseen"`` advantage. Both present cancel to normal (``resolve_mode``).
    # Empty defaults ⇒ normal (golden corpus unchanged).
    target_unseen: dict[str, bool] = field(default_factory=dict)
    attacker_unseen_by: dict[str, bool] = field(default_factory=dict)
    # Per-TARGET attacker→target distance in feet (``SpatialTopology.distance_ft``),
    # computed once per resolution by the orchestrator (``_target_distance_map``).
    # Consumed by ``attack.py`` for the SRD 5.2 Prone target row (advantage
    # within 5 ft, disadvantage otherwise). Absent target -> unknown -> that row
    # stays inert.
    target_distance_ft: dict[str, int] = field(default_factory=dict)
    # SRD 5.2 §Range (C15 Task 2): "Your attack roll has Disadvantage when
    # your target is beyond normal range, and you can't attack a target
    # beyond long range." Per-TARGET flag — True iff the attacker→target
    # distance is beyond the weapon's NORMAL band but still within its MAX
    # (long) band, projected once per resolution by the orchestrator from
    # ``_weapon_attack_range_ft`` + the live distance. The MAX-band reject
    # itself happens upstream (``_pc_attack_out_of_range``), before this
    # context is even built, so a target reaching ``attack.py`` with this
    # flag set is always a LEGAL, merely disadvantaged, attack. Consumed in
    # ``attack.py``, which appends the ``"range:long"`` disadvantage source.
    # Empty default keeps the golden corpus identical (no range geometry).
    target_beyond_normal_range: dict[str, bool] = field(default_factory=dict)
    # SRD 5.2 §Actions in Combat — Dodge (C14 Task 3). Per-TARGET whether the
    # Dodge benefit is currently active (``dodging`` AND not Incapacitated
    # AND Speed > 0 — the SRD loss clause), projected once per resolution by
    # the orchestrator (``_dodge_benefit_active``). Consumed in
    # ``attack.py``, which folds it into disadvantage on an attack roll
    # against that target. SRD also conditions the attack-disadvantage half
    # of Dodge on "if you can see the attacker" — that conjunct is deferred
    # to C16b (no vision model wired to this seam yet); the DEX-save
    # advantage half has no such conjunct and is folded separately via
    # ``passive_save_adv`` in the hydration payload. Empty default keeps the
    # golden corpus identical (no dodge geometry).
    target_dodging: dict[str, bool] = field(default_factory=dict)
    # SRD 5.2 §Actions in Combat — Help, Assist an Attack Roll (C14 Task 4).
    # Per-TARGET: does an outstanding Help grant against this target belong
    # to an ALLY of the attacker resolving THIS activity? Projected once per
    # resolution by the orchestrator (``live.help_grants`` cross-referenced
    # against the attacker's side); consumed in ``attack.py``, which folds it
    # into advantage on an attack roll against that target. The one-use pop
    # (the grant is spent even on a miss, or when cancelled to normal by a
    # disadvantage source — "the next attack roll") is an orchestrator-side
    # write after resolution, not this pure resolver's concern. Empty default
    # keeps the golden corpus identical (no Help geometry).
    target_help_advantage: dict[str, bool] = field(default_factory=dict)
    # The entity grappling the ATTACKER (SRD 5.2 Grappled: disadvantage on
    # attack rolls against any target other than the grappler). ``None`` when
    # not grappled or the grappler is unknown -> row inert.
    attacker_grappler_id: str | None = None
    # Per-ENTITY signed flat modifier applied to EVERY D20 Test the entity makes
    # (SRD 5.2 Exhaustion: "the roll is reduced by 2 times your Exhaustion
    # level" — ``rules.conditions.d20_test_penalty``). Keyed by entity_id; the
    # attacker reads its own entry in ``attack.py``, the saving creature in
    # ``save_primitive.py``, the checking actor in ``check.py``. Absent -> 0.
    # A flat modifier never adds a draw, so seeded streams are unmoved.
    d20_test_penalty: dict[str, int] = field(default_factory=dict)
    # Per-TARGET flat AC bonus from an active effect (Shield's +5, keyed
    # ``"system.attributes.ac.bonus"`` in the Foundry source data, aliased to
    # the engine's ``"ac.bonus"`` fold key). Mirrors ``passive_save_modifiers``'s
    # per-target int shape. Computed once per activity resolution by the
    # orchestrator (folded from ``live.active_effects`` via
    # ``_fold_active_effect_changes`` + extracted in ``build_activity_context``);
    # consumed in ``attack.py`` alongside the cover-AC fold, before the
    # ``total >= target_ac`` comparison. Absent target -> +0. Empty default
    # keeps the golden corpus identical .
    passive_ac_bonus: dict[str, int] = field(default_factory=dict)
    # Per-actor ability/skill-check modifier sidecar, mirroring
    # ``effects/check.py:_read_check_modifiers``'s shape
    # ``{entity_id: {"skills": {slug: mod}, "ability_mods": {ability: mod},
    # "disadvantage": bool}}``. The RESOLVED per-skill / per-ability integer
    # (ability modifier + proficiency bonus, doubled with Expertise), NOT rebuilt
    # here from ability score + proficiency; an absent actor / skill / ability
    # contributes +0. Projected by the orchestrator off the live ``Combatant``
    # (``_project_target_modifiers`` via ``activities.actor_stats.check_modifier``)
    # and threaded in by ``build_activity_context`` (F1d). ``disadvantage`` is the
    # condition-derived flag (Frightened / Poisoned / Exhaustion); since F2c it
    # is CONSUMED by ``check.py``, which feeds it to ``roll_d20_test`` as the
    # ``"condition:attacker"`` source (a flagged actor draws two d20s and keeps
    # the lower).
    # Heterogeneous by construction, hence the ``Any`` value type.
    check_modifiers: dict[str, dict[str, Any]] = field(default_factory=dict)
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
    # The CASTER's own active effects, consulted by ``attack.py`` for the
    # attacker-side ``flags.advantage.attack`` / ``flags.disadvantage.attack``
    # override changes (SRD §Advantage and Disadvantage). Mirrors the
    # attacker-flag half of ``rules/combat.py``'s already-implemented (but live-
    # path-orphaned) reconciliation. Supplied by the orchestrator (projected
    # from ``live.active_effects[caster_id]``) at cutover; by golden/e2e
    # fixtures now. Empty default keeps the golden corpus identical (no
    # advantage producer ⇒ every attack rolls ``normal``, as before).
    active_effects: Sequence[ActiveEffect] = ()
    # F2b — SRD §Advantage and Disadvantage, condition-derived half. The
    # CASTER's own active condition NAMES (``rules/conditions.active_condition_names``)
    # and the same per-target projection keyed by ``entity_id``. Consumed by
    # ``attack.py`` via ``rules/conditions.conditions_grant_advantage_on_attack``
    # (Invisible/Blinded/Poisoned/Frightened/Restrained on the attacker;
    # Paralyzed/Stunned/Unconscious/Blinded on the target). Filled by
    # ``build_activity_context`` from ``Combatant.conditions``; empty defaults
    # leave every attack at ``normal``, byte-identical to the pre-F2b stream.
    attacker_conditions: list[str] = field(default_factory=list)
    target_conditions: dict[str, list[str]] = field(default_factory=dict)
    # SRD §Sneak Attack (Rogue), "Once per turn" — per-ATTACKER gate keyed by
    # ``entity_id`` (mirrors ``passive_melee_damage_bonus``'s per-caster shape).
    # ``True`` means the caster has ALREADY landed a Sneak Attack rider this
    # turn, so the injection point in ``attack.py:_apply_on_hit_damage`` skips
    # the fold. The orchestrator populates it per intent from the live
    # ``Combatant.sneak_attack_spent_this_turn`` flag and clears that flag at
    # ``TurnStarted``. Absent caster ⇒ not spent (rider may fire). Empty default
    # keeps the golden corpus identical.
    sneak_attack_spent: dict[str, bool] = field(default_factory=dict)
    # SRD §Sneak Attack (Rogue), ally-adjacent alternative — per-TARGET flag
    # keyed by the target's ``entity_id``. ``True`` means at least one of the
    # caster's allies is within 5 ft of THAT target and is not Incapacitated,
    # so a Sneak Attack rider may fire without Advantage (provided the attacker
    # is not at Disadvantage). Computed once per resolution by the orchestrator
    # (a new consumer of the ``spatial.py`` distance seam, over the caster's
    # party allies) and passed in as plain data — the pure resolver never
    # touches the spatial seam. Absent target ⇒ no adjacent ally. Empty default
    # keeps the golden corpus identical.
    sneak_attack_ally_adjacent: dict[str, bool] = field(default_factory=dict)
    # Test-determinism seams (our own code): variables["force_d20"],
    # variables["force_save_d20"], variables["in_crit"].
    variables: dict[str, int] = field(default_factory=dict)
    # SRD 5.2 §Two-Weapon Fighting / Light property — "you don't add your
    # ability modifier to the extra attack's damage unless that modifier is
    # negative." Set True by the orchestrator only for an off-hand swing
    # (Task 2); ``_roll_base_weapon_damage`` (attack.py) zeroes a POSITIVE
    # governing-ability mod when this is set — a negative mod still applies.
    # False default keeps every other swing (main-hand, monster, spell)
    # byte-identical to before this field existed.
    suppress_positive_ability_damage_mod: bool = False

    def ability_mod(self, ability: str) -> int:
        return (self.caster_abilities.get(ability, 10) - 10) // 2
