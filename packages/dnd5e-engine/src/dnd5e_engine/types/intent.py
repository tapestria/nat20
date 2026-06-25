"""Host-agnostic intent types — canonical ActionType + CombatOutcome surface.

The library owns ActionType outright: this class is the single canonical
location for both the string values and the case-insensitive ``_missing_``
hook. Hosts that need case-insensitive lookup get it for free by importing
``ActionType`` from this module; there is no mixin, no parallel class.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ActionType(StrEnum):
    """All player action types recognized by the intent parser.

    Case-insensitive construction supported via ``_missing_`` —
    ``ActionType("ATTACK")`` and ``ActionType("attack")`` both yield
    ``ActionType.ATTACK``. The canonical ``.value`` is always the
    lower-cased declared string.
    """

    ATTACK = "attack"
    CAST_SPELL = "cast_spell"
    DODGE = "dodge"
    # SRD §Combat — Dash. Doubles the actor's movement budget for the current
    # turn. Default cost: Action. Rogues with Cunning Action may spend a Bonus
    # Action instead (parser signals via ``ParsedIntent.use_bonus_action``).
    DASH = "dash"
    FLEE = "flee"
    MOVE = "move"
    INTERACT_NPC = "interact_npc"
    # parser-uplift G-017: unfocused world-curiosity question ("what do I
    # know about the Tenebres?"). Schema-only at this commit — dispatch
    # wiring lands in subsequent tasks, parser prompt rule teaching when
    # to emit AMBIENT_INQUIRY ships in piece 6 (parser-prompt-rewrite).
    AMBIENT_INQUIRY = "ambient_inquiry"
    INTERACT_OBJECT = "interact_object"
    EXAMINE_LOCATION = "examine_location"
    QUEST_ACCEPT = "quest_accept"
    SKILL_CHECK = "skill_check"
    SHORT_REST = "short_rest"
    FREE_ROLEPLAY = "free_roleplay"
    OTHER = "other"
    EQUIP_ITEM = "equip_item"
    PREPARE_SPELL = "prepare_spell"
    # Invoke a single granted class/species feature activity (e.g. Rage,
    # Second Wind). Carries ``feature_id`` (the feature slug); the
    # orchestrator resolves it via ``get_feature`` gated to the caster's
    # ``granted_features`` repertoire and invokes its single typed Activity.
    USE_FEATURE = "use_feature"
    # Save-side active-effect applicability AND standalone saving-throw
    # dispatch. Phase 3a.1 wires a feature-flagged short-circuit branch
    # in engine_dispatch; the real handler that consumes ctx.active_effects
    # lands in Phase 3c. See docs/design/combat-state-contract.md §10.
    SAVING_THROW = "saving_throw"
    # Combat-only zone movement (per docs/design/combat-state-contract.md §10).
    # Phase 3a.1 wires a feature-flagged short-circuit branch in
    # engine_dispatch; the real handler lands in Phase 3c.
    ZONE_MOVE = "zone_move"
    # Wave 4: investigation-quest player primitives.
    # QUEST_RESOLUTION_ATTEMPT — player addresses an NPC to formally state
    # the quest resolution ("I tell Marta the killer is Aldric"). The
    # dispatch site (ws_player_action) cross-checks the addressed NPC
    # against the active quest's `payload.resolution_recipient_npc_ids`
    # AND against `turn_ctx.context_entity_ids`, then sets a per-turn flag
    # the QuestCompleted precondition gate reads.
    # CONSULT_CODEX — player consults the global Codex archive ("I check
    # the chronicles for Aldric's connections"). The dispatch site rolls
    # an Investigation skill_check directly (rules-engine pure path),
    # samples a record from the active-quest pool, and surfaces an
    # outcome facet to the narrator. No engine_dispatch hop.
    QUEST_RESOLUTION_ATTEMPT = "quest_resolution_attempt"
    CONSULT_CODEX = "consult_codex"

    @classmethod
    def _missing_(cls, value: Any) -> ActionType | None:
        """Case-insensitive member lookup."""
        if not isinstance(value, str):
            return None
        folded = value.lower()
        for member in cls:
            if member.value.lower() == folded:
                return member
        return None


class CombatOutcome(BaseModel):
    """Engine-resolved combat result.

    Carries both totals (10 required fields) and raw dice data (optional
    fields) for DiceOutcome broadcast construction by the caller.
    """

    # -- Totals (required) --
    hit: bool
    damage_dealt: int
    damage_type: str
    attack_roll: int
    target_ac: int
    is_critical: bool
    target_name: str
    target_hp_remaining: int
    target_hp_max: int
    target_died: bool

    # -- Raw dice data (optional) --
    raw_attack_roll_dice: list[int] = Field(default_factory=list)
    raw_attack_roll_modifier: int = 0
    raw_damage_dice: list[int] = Field(default_factory=list)
    raw_damage_modifier: int = 0
    raw_save_roll_total: int | None = None
    raw_save_dc: int | None = None
    raw_save_success: bool | None = None


class SkillOutcome(BaseModel):
    """Engine-resolved skill check result."""

    skill: str
    ability: str
    roll_total: int
    modifier: int
    dc: int | None = None
    success: bool | None = None  # None if no DC (contested)
    natural_roll: int = 0


class SavingThrowOutcome(BaseModel):
    """Engine-resolved standalone saving-throw result (SAVING_THROW, Phase 3c.1).

    The dispatch handler is pure (no I/O); the outcome carries enough
    detail for the async caller (ws_player_action / combat orchestration)
    to route the appropriate EffectStore call:

      - failed save + ``apply_on_fail_template_id`` -> EffectStore.apply_to_targets
      - successful save + ``source_effect_id`` -> EffectStore.expire (per-target clear)
      - failed concentration save + ``source_effect_id`` ->
        EffectStore.expire_effect_all_targets (cascade clear)

    Concentration scoping is the ``(source_entity_id, effect_id)`` pair
    per docs/design/combat-state-contract.md v9 locked input #1.
    """

    target_entity_id: str
    ability: str  # the save ability rolled (e.g. "wisdom")
    dc: int
    roll_total: int
    natural_roll: int  # the raw d20 face (or chosen die under adv/disadv)
    modifier: int  # ability modifier + (proficiency if proficient)
    success: bool
    # Source-effect scoping for expire / cascade routing (per-cast identity).
    source_effect_id: str | None = None
    source_entity_id: str | None = None
    # Effect template the caller applies when the save fails (e.g. Hold Person).
    apply_on_fail_template_id: str | None = None
    # When True, a failed save directs the caller to cascade-clear every
    # (source_entity_id, effect_id) edge across all targets.
    is_concentration_save: bool = False


__all__ = [
    "ActionType",
    "CombatOutcome",
    "SavingThrowOutcome",
    "SkillOutcome",
]
