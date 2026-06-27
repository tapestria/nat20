"""dnd5e-engine — host-agnostic D&D 5e SRD rules engine.

Public API per docs/superpowers/specs/2026-05-26-dnd5e-engine-extraction-design.md.

Asset loading runs through ``dnd5e_srd_data.BundledAssetLoader`` (the typed
2024-SRD corpus), wired via :mod:`dnd5e_engine.lib_loader`.

Deferred for later phases:
  - roll (ad-hoc dice) — Phase 7
  - get_state_snapshot / list_active_handles (diagnostic introspection)
    — not yet implemented in orchestrator; will land alongside Phase 5 or 6.
"""

from __future__ import annotations

__version__ = "0.1.1"

from dnd5e_engine.build_party import build_party_member
from dnd5e_engine.build_spec import (
    AbilityScores,
    CharacterBuildSpec,
    CombatInstance,
    make_build_spec,
)
from dnd5e_engine.check import CheckKind, CheckResult, CheckSpec, resolve_check
from dnd5e_engine.events import CombatEvent, IntentType
from dnd5e_engine.orchestrator import (
    CombatHandle,
    LiveCombatView,
    PlayerIntent,
    advance_monster_turn,
    end_combat,
    get_actor_active_effects,
    get_live,
    narration_events,
    start_combat,
    submit_player_intent,
)
from dnd5e_engine.outcome import (
    CombatOutcome,
    DeathRecord,
    LootDrop,
)
from dnd5e_engine.results import EndCombatResult, StartCombatResult
from dnd5e_engine.rules.effects import roll_dice_str
from dnd5e_engine.spatial import cell_id, parse_cell
from dnd5e_engine.specs import (
    EncounterMemberSpec,
    GridScene,
    PartyMemberSpec,
    SceneTopology,
    ZoneEdge,
)
from dnd5e_engine.types.effects import (
    ActiveEffect,
    ActiveEffectChange,
    ActiveEffectDuration,
)
from dnd5e_engine.types.intent import ActionType

__all__ = [
    "AbilityScores",
    "ActionType",
    "ActiveEffect",
    "ActiveEffectChange",
    "ActiveEffectDuration",
    "CharacterBuildSpec",
    "CheckKind",
    "CheckResult",
    "CheckSpec",
    "CombatEvent",
    "CombatHandle",
    "CombatInstance",
    "CombatOutcome",
    "DeathRecord",
    "EncounterMemberSpec",
    "EndCombatResult",
    "GridScene",
    "IntentType",
    "LiveCombatView",
    "LootDrop",
    "PartyMemberSpec",
    "PlayerIntent",
    "SceneTopology",
    "StartCombatResult",
    "ZoneEdge",
    "advance_monster_turn",
    "build_party_member",
    "cell_id",
    "end_combat",
    "get_actor_active_effects",
    "get_live",
    "make_build_spec",
    "narration_events",
    "parse_cell",
    "resolve_check",
    "roll_dice_str",
    "start_combat",
    "submit_player_intent",
]
