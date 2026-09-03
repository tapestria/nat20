"""dnd5e-engine — a host-agnostic, zero-I/O D&D 5e SRD 5.2 rules engine.

Everything exported here is listed in ``__all__`` below; that list is the
package's stable contract and is pinned by ``tests/test_public_api_surface.py``.

The four combat-loop coroutines are ``start_combat``, ``submit_player_intent``,
``advance_monster_turn`` and ``end_combat``; ``resolve_check`` is the standalone
ability/skill/saving-throw resolver, and ``build_party_member`` turns a
``CharacterBuildSpec`` into a combat-ready ``PartyMemberSpec``.

Rules content is never bundled with the engine. It is read at runtime from the
companion ``dnd5e-srd-data`` package; call ``configure_lib_loader`` to
substitute your own typed corpus.

See the ``docs/`` tree (published at https://tapestria.github.io/nat20/) for the
combat model, the activity corpus, and a per-mechanic capability matrix
describing exactly which SRD rules this engine resolves today.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

try:  # pragma: no cover - trivial packaging fallback
    __version__ = _pkg_version("dnd5e-engine")
except PackageNotFoundError:  # pragma: no cover - source tree without install
    __version__ = "0.0.0+unknown"

from dnd5e_engine.build_party import build_party_member
from dnd5e_engine.build_spec import (
    AbilityScores,
    CharacterBuildSpec,
    CombatInstance,
    derive_multiclass_slots,
    derive_spell_slots,
    make_build_spec,
)
from dnd5e_engine.check import CheckKind, CheckResult, CheckSpec, resolve_check
from dnd5e_engine.events import AdvantageSource, CombatEvent, IntentType
from dnd5e_engine.lib_loader import configure_lib_loader
from dnd5e_engine.orchestrator import (
    CombatHandle,
    IntentRejectedError,
    LiveCombatView,
    PlayerIntent,
    advance_monster_turn,
    drain_pending_events,
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
from dnd5e_engine.rest import (
    HitDicePool,
    RecoveryPeriod,
    RestOutcome,
    recover_feature_uses,
    recover_item_uses,
    resolve_long_rest,
    resolve_short_rest,
)
from dnd5e_engine.results import EndCombatResult, StartCombatResult
from dnd5e_engine.rules.effects import roll_dice_str
from dnd5e_engine.spatial import cell_id, parse_cell
from dnd5e_engine.specs import (
    EncounterMemberSpec,
    GridScene,
    PartyMemberSpec,
    SceneTopology,
    WallSegment,
    ZoneEdge,
)
from dnd5e_engine.spellcasting import derive_pact_slots
from dnd5e_engine.types.effects import (
    ActiveEffect,
    ActiveEffectChange,
    ActiveEffectDuration,
)

__all__ = [
    "AbilityScores",
    "ActiveEffect",
    "ActiveEffectChange",
    "ActiveEffectDuration",
    "AdvantageSource",
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
    "HitDicePool",
    "IntentRejectedError",
    "IntentType",
    "LiveCombatView",
    "LootDrop",
    "PartyMemberSpec",
    "PlayerIntent",
    "RecoveryPeriod",
    "RestOutcome",
    "SceneTopology",
    "StartCombatResult",
    "WallSegment",
    "ZoneEdge",
    "advance_monster_turn",
    "build_party_member",
    "cell_id",
    "configure_lib_loader",
    "derive_multiclass_slots",
    "derive_pact_slots",
    "derive_spell_slots",
    "drain_pending_events",
    "end_combat",
    "get_actor_active_effects",
    "get_live",
    "make_build_spec",
    "narration_events",
    "parse_cell",
    "recover_feature_uses",
    "recover_item_uses",
    "resolve_check",
    "resolve_long_rest",
    "resolve_short_rest",
    "roll_dice_str",
    "start_combat",
    "submit_player_intent",
]
