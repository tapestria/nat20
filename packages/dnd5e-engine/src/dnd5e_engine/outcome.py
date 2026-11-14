"""CombatOutcome data classes — the pure-data projection of closed combat state.

These models are the typed payload the public combat seam returns from
``end_combat``. Translating them into a host's own world events and
persisting them happen host-side; this module is host-free.

A typical host-side projection:

- Deaths → a death event per creature kind (character, NPC, monster). A
  character at 0 HP is not a death: it surfaces as residual HP 0 and only
  becomes a death through the death-save outcome path.
- Residual HP → a character HP change.
- Loot → an item transfer or an item creation, per the loot source.
- XP → an XP award per character.

End-of-combat condition carryover is retired; the authoritative
end-of-combat effect snapshot lives on
``EndCombatResult.final_active_effects`` (Foundry-aligned
``ActiveEffect`` rows). Persisting effects across combats is a host concern.
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
    # The creature that dealt the killing damage, whoever's turn it was;
    # ``None`` for failed death saves and for a creature that killed itself.
    killer_id: str | None = None


class KnockOutRecord(BaseModel):
    """SRD 5.2 Knocking Out a Creature: a creature a pulled melee blow left at
    1 Hit Point, Unconscious. ``attacker_id`` is the creature that dealt the
    blow."""

    model_config = ConfigDict(extra="forbid")

    target_id: str
    target_kind: Literal["character", "npc", "monster"]
    attacker_id: str | None


class LootDrop(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # ``from_id`` for transferred items (existing item moves out of a
    # dead combatant); ``location_id`` for created items (loot fabricated
    # at scene). Exactly one of the two source modes per drop, decided
    # by ``source``.
    source: LootSource
    item_id: str  # canonical id ("item:hex12") — must exist for transfer mode
    to_id: str  # "char:…" | "npc:…" | "loc:…" — the host validates the prefix
    quantity: int = 1
    # Created-mode-only metadata (ignored for transfer mode):
    location_id: str | None = None
    name: str | None = None
    item_type: str | None = None


class CombatOutcome(BaseModel):
    """Complete projection of closed combat state into world mutations.

    Every field is the "what should change in the host's world" payload
    for one mutation category; a host translates each into its own events
    and persists them.
    """

    model_config = ConfigDict(extra="forbid")

    handle_id: str
    ended_reason: EndedReason

    deaths: list[DeathRecord] = Field(default_factory=list)
    # combatant_id → HP at combat end (a host typically persists it for
    # characters only; monster and NPC HP at combat end is ephemeral).
    residual_hp: dict[str, int] = Field(default_factory=dict)
    residual_temp_hp: dict[str, int] = Field(default_factory=dict)
    loot_drops: list[LootDrop] = Field(default_factory=list)
    xp_awarded: dict[str, int] = Field(default_factory=dict)
    # pc_id → {slot_level_or_feature: count_used}
    expended_resources: dict[str, dict[str, int]] = Field(default_factory=dict)
    # Creatures still Unconscious from a knock-out when the combat ended, in
    # the order they were knocked out. A creature that woke or died is not here.
    knock_outs: list[KnockOutRecord] = Field(default_factory=list)


__all__ = [
    "CombatOutcome",
    "DeathReason",
    "DeathRecord",
    "EndedReason",
    "KnockOutRecord",
    "LootDrop",
    "LootSource",
]
