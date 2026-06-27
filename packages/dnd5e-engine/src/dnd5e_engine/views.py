"""Public read-model for live combat state.

``get_live`` returns a :class:`LiveCombatView` — a point-in-time snapshot
projection of the engine's private ``_LiveCombat``. Host-side resolvers
that run alongside the engine's dispatch consume this stable surface,
never the private dataclass. Container fields are copied (outer + inner)
so the view does not observe later engine mutations; the ``Combatant`` and
``CombatOutcome`` items are shared references (the host reads, never
mutates them).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from dnd5e_engine.outcome import CombatOutcome
from dnd5e_engine.types.combat import Combatant

if TYPE_CHECKING:
    from dnd5e_engine.orchestrator import _LiveCombat


@dataclass(frozen=True)
class LiveCombatView:
    """Snapshot projection of live combat state for host consumers."""

    initiative: list[Combatant]
    party_ids: set[str]
    encounter_ids: set[str]
    dead_ids: set[str]
    tracked_hp: dict[str, int]
    tracked_temp_hp: dict[str, int]
    active_conditions: dict[str, set[str]]
    actor_zone: dict[str, str]
    spell_slots_by_entity: dict[str, dict[int, int]]
    spells_known_by_entity: dict[str, list[str]]
    current_turn_index: int
    round_number: int
    ended: bool
    final_outcome: CombatOutcome | None

    @classmethod
    def from_live(cls, live: _LiveCombat) -> LiveCombatView:
        return cls(
            initiative=list(live.initiative),
            party_ids=set(live.party_ids),
            encounter_ids=set(live.encounter_ids),
            dead_ids=set(live.dead_ids),
            tracked_hp=dict(live.tracked_hp),
            tracked_temp_hp=dict(live.tracked_temp_hp),
            active_conditions={k: set(v) for k, v in live.active_conditions.items()},
            actor_zone=dict(live.actor_zone),
            spell_slots_by_entity={k: dict(v) for k, v in live.spell_slots_by_entity.items()},
            spells_known_by_entity={k: list(v) for k, v in live.spells_known_by_entity.items()},
            current_turn_index=live.current_turn_index,
            round_number=live.round_number,
            ended=live.ended,
            final_outcome=live.final_outcome,
        )
