"""Combat participant types — ``Combatant`` and ``BehaviorProfile``.

Host-agnostic value types: stdlib + pydantic + the engine's own
``ActiveCondition``, plus the dataset schema import
``dnd5e_srd_data.schema.monster.MonsterTraitMechanic``. ``Combatant`` is the
engine's per-creature runtime combat state; hosts read it through
``dnd5e_engine.views.LiveCombatView``.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from dnd5e_srd_data.schema.monster import MonsterTraitMechanic
from pydantic import BaseModel, Field, model_validator

from dnd5e_engine.activities.passive_stats import CombatantMovementModes, CombatantSenses
from dnd5e_engine.types.conditions import ActiveCondition


class BehaviorProfile(StrEnum):
    """Monster AI posture consumed by the orchestrator's flee heuristic."""

    AGGRESSIVE = "AGGRESSIVE"
    RANGED = "RANGED"
    DEFENSIVE = "DEFENSIVE"


class Combatant(BaseModel):
    entity_id: str
    entity_type: str  # "Character" | "Monster" | "NPC"
    name: str
    initiative: int
    hp_current: int
    # SRD §Temporary Hit Points; canonical hydration surface for the temphp evaluator
    temp_hp: int = 0
    is_alive: bool = True
    conditions: list[ActiveCondition] = Field(default_factory=list)
    # Extended combat stats (populated at combat start)
    hp_max: int = 0
    ac: int = 10
    # C15 (2026-09-02) — widened to ``int | None`` (was ``int = 0``). ``None``
    # means the host never explicitly set ``PartyMemberSpec.attack_bonus``;
    # ``activities/build_context.py``'s ``attack_bonus_override`` threads this
    # verbatim into ``ActivityResolutionContext``, and ``activities/attack.py``
    # already treats ``None`` as "no override" — so an unset PC now correctly
    # falls through to the real governing-ability-mod + proficiency-bonus
    # computation (SRD §Weapon Proficiency gate) instead of being silently
    # pinned to a 0 to-hit bonus. A host-supplied value (including a
    # real monster's, always threaded as a concrete int) is unaffected —
    # byte-identical to every pre-C15 fixture. Every direct arithmetic reader
    # (``build_context._caster_mod`` / ``_save_dc``, the two opportunity-
    # attack fire sites in ``orchestrator.py``) guards with ``or 0``.
    attack_bonus: int | None = None
    damage_dice: str = "1d4"  # "XdY+Z" format
    damage_type: str = "bludgeoning"
    behavior_profile: str = "AGGRESSIVE"  # BehaviorProfile value
    strength: int = 10
    dexterity: int = 10
    constitution: int = 10
    intelligence: int = 10
    wisdom: int = 10
    charisma: int = 10
    # F1 (2026-08-26): proficiency projection. Defaults keep every pre-F1
    # fixture byte-identical: no proficiencies → ability modifier only.
    proficiency_bonus_override: int | None = None  # monsters: template PB by CR
    save_proficiencies: list[str] = Field(default_factory=list)  # Ability codes
    skill_proficiencies: list[str] = Field(default_factory=list)  # skill slugs
    skill_expertise: list[str] = Field(default_factory=list)
    # C15 (2026-09-02) R1 sentinel — SRD 5.2 §Weapon Proficiency: "Anyone can
    # wield a weapon, but you must have proficiency with it to add your
    # Proficiency Bonus to an attack roll you make with it" (Proficiency
    # Bonus is OMITTED, never subtracted, when unproficient). ``None`` means
    # the host never set ``PartyMemberSpec.weapon_proficiencies`` — "assume
    # proficient", reproducing every pre-C15 fixture byte-identically. An
    # explicit list (possibly empty — "proficient in nothing") switches on
    # real enforcement: proficient iff the weapon's ``weapon_category`` or
    # ``slug`` appears in the list. Monsters never carry this field
    # explicitly, so it stays ``None`` -> always proficient, matching the SRD
    # "a monster is proficient with any weapon in its stat block" rule.
    weapon_proficiencies: list[str] | None = None  # categories + slugs; None = legacy sentinel
    death_saves: dict[str, Any] = Field(default_factory=dict)  # serialized DeathSaveState
    # SRD §Creatures — creature_type (e.g. "humanoid", "undead", "construct",
    # "elf"). Drives type-gated spell semantics (Hold Person targets only
    # humanoids; Sleep autopasses undead/elves; etc.). Populated from
    # MonsterTemplate.creature_type on Neo4j for monsters; PCs default to
    # ``None`` until the character-sheet projection lands. Read by the
    # condition-predicate evaluator via ``target.creature_type``.
    creature_type: str | None = None
    # SRD §Damage Resistance / §Damage Immunity — per-creature lists of damage
    # type slugs (lower-case SRD 5.1 types: acid, bludgeoning, cold, fire, force,
    # lightning, necrotic, piercing, poison, psychic, radiant, slashing, thunder).
    # Hydrated from MonsterTemplate.damage_resistances / damage_immunities (via
    # CombatMonster / CombatNPC) and projected into the orchestrator's
    # ``passive_damage_modifiers`` sidecar so the damage handler can apply
    # halving / zeroing without relying solely on the SRD-condition projection
    # (Petrified). PCs default to empty until the character-sheet projection
    # lands.
    damage_resistances: list[str] = Field(default_factory=list)
    damage_immunities: list[str] = Field(default_factory=list)
    # SRD §Damage Vulnerability — per-creature type list ("applying twice the
    # normal damage"). Unlike resistances/immunities this has NO
    # condition-derived source; it is hydrated from the monster template
    # (skeleton → ``["bludgeoning"]``) or a PC spec and folded into the
    # orchestrator's ``passive_damage_modifiers[...]["vulnerabilities"]`` sidecar
    # by ``_project_target_modifiers`` . Empty by default.
    damage_vulnerabilities: list[str] = Field(default_factory=list)
    # SRD §Condition Immunity — condition slugs this creature can't suffer
    # (Nature's Ward → ``"poisoned"``). Projected from PC always-on feature
    # ``system.traits.ci.value`` changes via ``build_party_member`` →
    # ``PartyMemberSpec.condition_immunities`` and copied here at start_combat;
    # monster/NPC templates thread theirs through the spec. The condition-
    # application path (``activities/effects.py::apply_activity_effects``)
    # suppresses a ``ConditionApplied`` whose condition is in this list
    # . Empty by default. NOTE: distinct from the dead, host-supplied
    # legacy dispatch surface's ``condition_immunities`` (removed in 0.5.0).
    condition_immunities: list[str] = Field(default_factory=list)
    # SRD §Senses — special senses in feet (darkvision/blindsight/tremorsense/
    # truesight). Projected from PC species + always-on feature passive_effects
    # via ``build_party_member`` → ``PartyMemberSpec.senses`` and copied here at
    # start_combat. Defaults to an empty ``CombatantSenses`` (no special senses)
    # for monsters / fixtures until a sense projection lands.
    senses: CombatantSenses = Field(default_factory=CombatantSenses)
    # SRD §Concentration — the effect_id this combatant is concentrating on,
    # if any. ``None`` when not concentrating. Hydrated by the orchestrator
    # into ``the host effect store`` for the SRD single-conc
    # rule + damage-driven CON-save probe in ``app/combat/effects/spell.py``.
    concentration_effect_id: str | None = None
    # SRD §Cantrips / §Character Advancement — character level (1..20). Drives
    # cantrip scaling tiers (1/5/11/17) for both dice-count (Sacred Flame,
    # Fire Bolt) and beam-count (Eldritch Blast) modes. Defaults to 1 for
    # NPCs/monsters and any caller that does not project a PC level.
    character_level: int = 1
    # SRD §Action Economy — every turn a creature has one Action, one Bonus
    # Action, and one Reaction. The reaction regenerates at the start of the
    # actor's own turn ("You regain your reaction at the start of your turn").
    # Set False on consumption, reset True on the actor's own TurnStarted.
    action_available: bool = True
    bonus_action_available: bool = True
    reaction_available: bool = True
    # SRD §Movement — a creature's walking speed in feet (used as the per-turn
    # movement budget). ``base_speed`` is the constant max (set at combat
    # start from Character race / MonsterTemplate.speed.walk; defaults to 30
    # — the SRD baseline for human-sized creatures). ``movement_remaining``
    # is the per-turn budget, reset to ``base_speed`` on the actor's own
    # TurnStarted and decremented by each successful MOVE intent.
    base_speed: int = 30
    movement_remaining: int = 30
    # SRD §Movement — non-walk movement modes (climb/swim/fly/burrow speeds in
    # feet; ``None`` = mode unavailable). Projected from a PC's always-on
    # granted-feature ``system.attributes.movement.*`` changes via
    # ``build_party_member`` → ``PartyMemberSpec.movement_modes`` and copied here
    # at start_combat (Roving → climb/swim = walk speed). Kept multi-mode
    # (collapsing to a scalar is lossy). Empty by default for monsters/fixtures.
    movement_modes: CombatantMovementModes = Field(default_factory=CombatantMovementModes)
    # SRD §Opportunity Attacks — the actor's melee reach in feet (the
    # distance at which an opponent leaving "reach" triggers an AoO).
    # Defaults to 5ft (standard unarmed / 1-handed melee weapon). Polearms
    # with the reach property (glaive, halberd, pike, lance) project 10ft
    # here. Distinct from per-attack reach (carried on the weapon IR); this
    # field is the AoO-trigger threshold and is the only reach value the
    # opportunity-attack detection in advance_monster_turn reads.
    melee_reach_ft: int = 5
    # SRD §Classes — character class slug for PCs (e.g. "rogue", "barbarian").
    # Drives class-feature gating in the orchestrator — currently the Cunning
    # Action Dash path (Rogue-only) consults this. ``None`` for monsters / NPCs
    # / fixtures that do not project class info.
    class_slug: str | None = None
    # SRD §Subclasses — subclass slug for PCs (e.g. "berserker"). Copied from
    # ``PartyMemberSpec.subclass_slug`` at start_combat so subclass-feature
    # activities (piece 4) can gate on it. ``None`` for monsters / NPCs /
    # fixtures / graph PCs without a persistent subclass source.
    subclass_slug: str | None = None
    # SRD §Species — species slug for PCs (e.g. "orc", "dragonborn"). Copied
    # from ``PartyMemberSpec.species_slug`` at start_combat so species-feature
    # activities resolve through the same USE_FEATURE repertoire gate as
    # class/subclass features, and species @scale tables (e.g. Dragonborn
    # breath) resolve. ``None`` for monsters / NPCs / fixtures / graph PCs
    # without a persistent species source.
    species_slug: str | None = None
    # SRD §Hellish Rebuke — *"the creature that damaged you"*. Tracks the
    # most-recent source_id from a DamageApplied targeting this combatant.
    # ``None`` until first damage; cleared at TurnStarted is intentionally
    # NOT done (the trigger rule is about damage taken this round, but the
    # cast must follow the damaging event directly — keeping the field
    # across turns lets HR validate against the last damager regardless of
    # round boundaries until a more complete trigger model lands).
    last_damaged_by: str | None = None
    # SRD §Actions in Combat, Disengage — "Your movement doesn't provoke
    # Opportunity Attacks for the rest of the turn." Set True by
    # ``_handle_disengage`` (orchestrator.py, ; consulted by the
    # monster-reactor opportunity-attack scan
    # (``_fire_monster_opportunity_attacks_on_move``) to suppress AoOs for the
    # remainder of the turn. Reset to False at the actor's own TurnStarted,
    # alongside action_available/bonus_action_available/reaction_available.
    disengaging_this_turn: bool = False
    # SRD §Sneak Attack (Rogue), "Once per turn" — True once this combatant has
    # already dealt Sneak Attack damage during the current turn. Gates the
    # rider fold in ``activities/attack.py`` (projected per intent into
    # ``ActivityResolutionContext.sneak_attack_spent``). Reset to False at the
    # actor's own TurnStarted, alongside action_available / bonus_action_available
    # / reaction_available / disengaging_this_turn. Defaults False (rider may
    # fire) for every combatant.
    sneak_attack_spent_this_turn: bool = False
    # SRD §Extra Attack — "you can attack twice, instead of once, whenever
    # you take the Attack action on your turn" (and thrice/four-times at
    # higher tiers). The remaining main-hand swings this Action; refreshed
    # to ``_attacks_per_action(current)`` at the actor's own TurnStarted,
    # decremented once per resolved main-hand attack. 1 for every combatant
    # without a qualifying Extra Attack feature (the SRD default).
    attacks_remaining: int = 1
    # SRD §Action Economy — True once this turn's Attack action has
    # consumed its Action (the FIRST main-hand swing of a multi-attack
    # sequence). Gates whether a subsequent same-turn attack intent still
    # owes the Action budget (soft-consume: only the first swing pays).
    # Reset to False at the actor's own TurnStarted.
    attack_action_engaged: bool = False
    # SRD §Two-Weapon Fighting (Task 2) — the main-hand weapon's slug when
    # the just-resolved main-hand attack used a Light melee weapon,
    # opening the "attack again with a different Light weapon" off-hand
    # window. ``None`` closes the window (no Light main-hand swing yet
    # this turn). Reset to ``None`` at the actor's own TurnStarted.
    light_weapon_swing_slug: str | None = None
    # SRD §Two-Weapon Fighting (Task 2) — True once the Bonus Action
    # off-hand attack has been made this turn, closing the TWF window for
    # any further off-hand swing. Reset to False at the actor's own
    # TurnStarted.
    offhand_attack_spent: bool = False
    # SRD §Actions in Combat — Dodge (C14 Task 3). True for the remainder of
    # this turn and "until the start of your next turn": while active, any
    # attack roll made against this combatant has Disadvantage if the
    # attacker can see it (C16b: gated via ``orchestrator.py::
    # _combatant_can_see``, see ``activities/attack.py``) and it makes
    # Dexterity saving throws with Advantage. Lost early if Incapacitated or
    # Speed 0 (SRD loss clause;
    # see ``_dodge_benefit_active`` in orchestrator.py). Reset to False at
    # the actor's own TurnStarted — the exact SRD expiry point.
    dodging: bool = False
    # SRD 5.2 §Actions in Combat — Hide (final-review fix F3). Although Hide
    # touches no Action-economy budget (``_handle_hide``'s docstring), the
    # SRD frames it as taking "the Hide action" — a single attempt, not a
    # retry loop against an unresolved DC 15 Dexterity (Stealth) check.
    # True once a gated-through Hide attempt (success OR failure) has been
    # made this turn; a second attempt is rejected
    # (``IntentRejectedError("no_action_economy")``) with zero d20 draws.
    # Reset to False at the actor's own TurnStarted, alongside dodging.
    hide_attempted_this_turn: bool = False
    # C22: typed SRD 5.2 monster traits hydrated from the template's
    # ``special_abilities[].mechanic`` (Magic Resistance → advantage on saves
    # against spells in ``activities/save_primitive.py``; C18 consumes Pack
    # Tactics / Sunlight Sensitivity / Undead Fortitude / Regeneration …).
    # Empty for PCs and template-less foes.
    trait_mechanics: list[MonsterTraitMechanic] = Field(default_factory=list)
    # C22: how to read B/P/S entries in ``damage_resistances``. True (default
    # for host-authored specs) = SRD 5.1 stat-block convention "… from
    # nonmagical attacks": a magical weapon's or a spell's Bludgeoning /
    # Piercing / Slashing damage bypasses the resistance. False = the
    # resistance is unconditional (SRD 5.2 stat blocks; Foundry
    # ``dr.bypasses == []``). C18's corpus hydration sets it from
    # ``dr.bypasses``.
    physical_resistances_nonmagical_only: bool = True
    # SRD 5.2 Loading — "You can fire only one piece of ammunition from a
    # Loading weapon when you use an action, a Bonus Action, or a Reaction
    # to fire it, regardless of the number of attacks you can normally
    # make." Engine reading: one fire per TURN, not per action-type — no
    # PC reaction-attack path exists, so action/bonus/reaction collapse to
    # the turn boundary; the cap is per-actor (not per-weapon), matching
    # the SRD's "you" framing. Set True after any resolved main-hand OR
    # off-hand swing with a ``WeaponProperty.LOADING`` weapon (C15 Task
    # 5). Reset to False at the actor's own TurnStarted, alongside the
    # other per-turn attack-economy fields above.
    loading_weapon_fired_this_turn: bool = False
    # SRD 5.2 §Weapon Mastery — Cleave: "You can make this extra attack only
    # once per turn." Set True by the orchestrator once a cleave chain has
    # FIRED this turn (the extra attack roll was made, hit or miss); gates
    # ``ActivityResolutionContext.cleave_available`` for every later swing
    # this turn. Reset to False at the actor's own TurnStarted, alongside
    # the other per-turn attack-economy fields above (C15 Task 7).
    cleave_spent_this_turn: bool = False

    @model_validator(mode="before")
    @classmethod
    def migrate_string_conditions(cls, values: Any) -> Any:
        """Backward compat: coerce list[str] conditions to list[ActiveCondition].

        Handles stale host storage sessions with schema_version < 11 (T-01-03 mitigation).
        """
        conditions = values.get("conditions") if isinstance(values, dict) else None
        if isinstance(conditions, list) and conditions and isinstance(conditions[0], str):
            values = dict(values)
            values["conditions"] = [
                {
                    "condition": c,
                    "source_entity_id": "implied:migration",
                    "scope": "combat",
                    "applied_round": 0,
                }
                for c in conditions
            ]
        return values


__all__ = [
    "BehaviorProfile",
    "Combatant",
]
