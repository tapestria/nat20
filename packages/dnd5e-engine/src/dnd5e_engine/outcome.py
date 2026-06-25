"""CombatOutcome data classes — the pure-data projection of closed combat state.

These models are the typed payload the public combat seam returns from
``end_combat``. Translation into Tapestria's ``AnyWorldEvent`` discriminated
union and persistence via the event pipeline live host-side in
``app.session.combat_outcome``; this module is host-free.

Event-type mapping (host-side projection):

- Deaths → ``CharacterDied`` (PCs) / ``NpcDied`` (NPCs) / ``MonsterDied``
  (monsters). There is no ``CharacterUnconscious`` event; PCs at 0 HP
  surface via ``CharacterHpChanged(new_hp=0, …)`` and only escalate to
  ``CharacterDied`` via the death-save outcome path.
- Residual HP → ``CharacterHpChanged``.
- Loot → ``ItemTransferred`` / ``ItemCreated`` per the loot source.
- XP → ``CharacterXpAwarded``.

Phase 6: end-of-combat condition carryover is retired; the authoritative
end-of-combat effect snapshot lives on
``EndCombatResult.final_active_effects`` (Foundry-aligned
``ActiveEffect`` rows). Phase 6 callers log-and-discard; persistence is
[effects-cross-combat].
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DeathReason = Literal["damage", "death_saves", "instant_kill"]
EndedReason = Literal["victory", "defeat_tpk", "flee", "forced"]
LootSource = Literal["transfer", "created"]


class DeathRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_id: str
    target_kind: Literal["character", "npc", "monster"]
    location_id: str
    reason: DeathReason
    killer_id: str | None = None


class LootDrop(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # ``from_id`` for transferred items (existing item moves out of a
    # dead combatant); ``location_id`` for created items (loot fabricated
    # at scene). Exactly one of the two source modes per drop, decided
    # by ``source``.
    source: LootSource
    item_id: str  # canonical id ("item:hex12") — must exist for transfer mode
    to_id: str  # "char:…" | "npc:…" | "loc:…" — pipeline validates prefix
    quantity: int = 1
    # ``ItemCreated``-only metadata (ignored for transfer mode):
    location_id: str | None = None
    name: str | None = None
    item_type: str | None = None


class CombatOutcome(BaseModel):
    """Complete projection of closed combat state into world mutations.

    Every field is the "what should change in the world graph" payload
    for one mutation category; ``project_outcome_to_events`` (host-side)
    translates them to typed ``WorldEvent`` instances and ``apply_outcome``
    flows them through ``persist_and_apply``.
    """

    model_config = ConfigDict(extra="forbid")

    handle_id: str
    ended_reason: EndedReason

    deaths: list[DeathRecord] = Field(default_factory=list)
    # combatant_id → HP at combat-end (only emitted as CharacterHpChanged
    # for characters; monster/NPC HP at combat-end is not persisted to
    # graph by this seam — that ephemeral state is owned by combat Redis).
    residual_hp: dict[str, int] = Field(default_factory=dict)
    residual_temp_hp: dict[str, int] = Field(default_factory=dict)
    loot_drops: list[LootDrop] = Field(default_factory=list)
    xp_awarded: dict[str, int] = Field(default_factory=dict)
    # pc_id → {slot_level_or_feature: count_used}
    expended_resources: dict[str, dict[str, int]] = Field(default_factory=dict)


__all__ = [
    "CombatOutcome",
    "DeathReason",
    "DeathRecord",
    "EndedReason",
    "LootDrop",
    "LootSource",
]
