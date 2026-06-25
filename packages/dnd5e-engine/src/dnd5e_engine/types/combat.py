"""Combat participant types — Combatant + CombatNPC.

Moved from `backend/app/models/session.py` as part of the dnd5e-engine Phase 3
extraction. Host-agnostic; depends only on stdlib + pydantic + the library's
own `ActiveCondition`.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator

from dnd5e_engine.activities.passive_stats import CombatantSenses
from dnd5e_engine.types.conditions import ActiveCondition


class CombatNPC(BaseModel):
    """Ephemeral sidecar record for an NPC in combat. Lives in Redis only;
    cleared at end of combat. Owns template-derived combat stats that don't
    fit on the narrow Combatant: saves, resistances, immunities, ability
    scores, behavior_profile. Symmetric to CombatMonster for non-Character
    entities."""

    npc_id: str  # persistent NPC node ID (npc:hex12)
    template_id: str  # MonsterTemplate node ID used at materialization
    name: str
    hp_current: int
    hp_max: int
    ac: int
    attack_bonus: int
    damage_dice: str
    damage_type: str
    has_ranged_attack: bool = False
    dexterity: int = 10
    strength: int = 10
    constitution: int = 10
    wisdom: int = 10
    intelligence: int = 10
    charisma: int = 10
    behavior_profile: str = "AGGRESSIVE"
    damage_resistances: list[str] = Field(default_factory=list)
    damage_immunities: list[str] = Field(default_factory=list)
    is_alive: bool = True


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
    attack_bonus: int = 0
    damage_dice: str = "1d4"  # "XdY+Z" format
    damage_type: str = "bludgeoning"
    behavior_profile: str = "AGGRESSIVE"  # BehaviorProfile value
    strength: int = 10
    dexterity: int = 10
    constitution: int = 10
    intelligence: int = 10
    wisdom: int = 10
    charisma: int = 10
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
    # SRD §Senses — special senses in feet (darkvision/blindsight/tremorsense/
    # truesight). Projected from PC species + always-on feature passive_effects
    # via ``build_party_member`` → ``PartyMemberSpec.senses`` and copied here at
    # start_combat. Defaults to an empty ``CombatantSenses`` (no special senses)
    # for monsters / fixtures until a sense projection lands.
    senses: CombatantSenses = Field(default_factory=CombatantSenses)
    # SRD §Concentration — the effect_id this combatant is concentrating on,
    # if any. ``None`` when not concentrating. Hydrated by the orchestrator
    # into ``EffectStore._existing_concentration`` for the SRD single-conc
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

    @model_validator(mode="before")
    @classmethod
    def migrate_string_conditions(cls, values: Any) -> Any:
        """Backward compat: coerce list[str] conditions to list[ActiveCondition].

        Handles stale Redis sessions with schema_version < 11 (T-01-03 mitigation).
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
    "CombatNPC",
    "Combatant",
]
