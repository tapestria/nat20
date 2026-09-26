"""Public read-model for live combat state.

``get_live`` returns a ``LiveCombatView`` — a point-in-time snapshot
projection of the engine's private ``_LiveCombat``. Host-side resolvers
that run alongside the engine's dispatch consume this stable surface,
never the private dataclass. Container fields are copied (outer + inner)
so the view does not observe later engine mutations; the ``Combatant`` and
``CombatOutcome`` items are shared references (the host reads, never
mutates them).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from dnd5e_engine.outcome import CombatOutcome
from dnd5e_engine.types.combat import Combatant

if TYPE_CHECKING:
    from dnd5e_engine.orchestrator import _LiveCombat


@dataclass(frozen=True)
class ConstructView:
    """Read-only projection of one caster-owned spell construct (C21): SRD 5.2
    Spiritual Weapon's force. Not a combatant: it has no initiative slot, no
    HP and never appears in ``initiative`` or ``actor_zone``."""

    construct_id: str
    owner_id: str
    spell_id: str
    zone_id: str
    slot_level: int


@dataclass(frozen=True)
class TurnCombatView:
    """Per-current-actor turn-state projection (spec §6 row D2)."""

    attacks_remaining: int
    # SRD 5.2 Action Surge — the current actor's unspent additional actions
    # this turn (C20); 0 when none, when combat has ended or with no actor.
    extra_actions_remaining: int = 0


@dataclass(frozen=True)
class MonsterActionUsesView:
    """Read-only projection of one ``MonsterActionUses`` (C18)."""

    recharge_spent: bool
    uses_remaining: dict[str, int]


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
    pact_slots_by_entity: dict[str, dict[int, int]]
    spells_known_by_entity: dict[str, list[str]]
    custom_counters_by_entity: dict[str, dict[str, dict[str, int]]]
    current_turn_index: int
    round_number: int
    ended: bool
    final_outcome: CombatOutcome | None
    # SRD §Concentration — caster_id -> [(target_id, effect_id, origin), …];
    # the host-readable projection of the engine's concentration ownership
    # (C13, API-DELTAS). Empty dict when nobody concentrates.
    concentration_chain: dict[str, list[tuple[str, str, str]]]
    # C14 — the current actor's per-Action attack budget (spec §6 row D2).
    # ``TurnCombatView(attacks_remaining=0)`` when combat has ended or the
    # initiative order is empty (no current actor to project).
    turn: TurnCombatView
    # C18 — per-monster limited-use state (recharge actions, N/Day trait
    # uses), keyed entity_id -> action slug -> its use state. Absent entries
    # mean "no limited-use actions tracked for this entity".
    monster_action_uses_by_entity: dict[str, dict[str, MonsterActionUsesView]]
    # C18 — Legendary Actions / Legendary Resistance REMAINING pools, keyed
    # entity_id. Only monsters with a non-empty pool (``…_max > 0``) appear;
    # PCs and template-less foes are absent.
    legendary_actions_by_entity: dict[str, int]
    legendary_resistances_by_entity: dict[str, int]
    # C21 — caster-owned spell constructs keyed by ``construct_id``; empty when
    # none is live.
    constructs: dict[str, ConstructView] = field(default_factory=dict)

    @classmethod
    def from_live(cls, live: _LiveCombat) -> LiveCombatView:
        turn = TurnCombatView(attacks_remaining=0)
        if not live.ended and 0 <= live.current_turn_index < len(live.initiative):
            actor = live.initiative[live.current_turn_index]
            turn = TurnCombatView(
                attacks_remaining=actor.attacks_remaining,
                extra_actions_remaining=actor.extra_actions_remaining,
            )
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
            pact_slots_by_entity={k: dict(v) for k, v in live.pact_slots_by_entity.items()},
            spells_known_by_entity={k: list(v) for k, v in live.spells_known_by_entity.items()},
            custom_counters_by_entity={
                entity_id: {key: dict(counter) for key, counter in counters.items()}
                for entity_id, counters in live.custom_counters_by_entity.items()
            },
            current_turn_index=live.current_turn_index,
            round_number=live.round_number,
            ended=live.ended,
            final_outcome=live.final_outcome,
            concentration_chain={k: list(v) for k, v in live.concentration_chain.items()},
            turn=turn,
            monster_action_uses_by_entity={
                entity_id: {
                    slug: MonsterActionUsesView(
                        recharge_spent=uses.recharge_spent,
                        uses_remaining=dict(uses.uses_remaining),
                    )
                    for slug, uses in by_slug.items()
                }
                for entity_id, by_slug in live.monster_action_uses_by_entity.items()
            },
            legendary_actions_by_entity={
                c.entity_id: c.legendary_actions_remaining
                for c in live.initiative
                if c.legendary_actions_max
            },
            legendary_resistances_by_entity={
                c.entity_id: c.legendary_resistances_remaining
                for c in live.initiative
                if c.legendary_resistances_max
            },
            constructs={
                cid: ConstructView(
                    construct_id=cid,
                    owner_id=c.owner_id,
                    spell_id=c.spell_id,
                    zone_id=c.cell,
                    slot_level=c.slot_level,
                )
                for cid, c in live.constructs.items()
            },
        )


__all__ = ["ConstructView", "LiveCombatView", "MonsterActionUsesView", "TurnCombatView"]
