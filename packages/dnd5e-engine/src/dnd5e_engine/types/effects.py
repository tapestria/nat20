"""D&D 5e Active Effects — Foundry VTT dnd5e-aligned schema.

Phase 6 of the dnd5e-engine extraction: the prior `effect_id` /
`source_entity_id` / `rounds_remaining` / `modifiers: list[EffectModifier]`
shape is replaced by the Foundry-aligned model. `EffectModifier` and
`EffectRef` retire.

Reference: /tmp/foundry-dnd5e/module/documents/active-effect.mjs and
/tmp/foundry-dnd5e/module/data/active-effect/. Foundry's structural
choices (statuses-set replaces bridge-conditions, structured duration,
changes[] with mode/value/priority, origin UUID) carry over verbatim
where applicable. The `changes[].key` vocabulary uses Tapestria's flat
namespace ("attack.roll.bonus", "save.wisdom.bonus",
"flags.advantage.<bucket>"), not Foundry's Actor-data dotted paths.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ChangeMode = Literal["custom", "multiply", "add", "downgrade", "upgrade", "override"]


class ActiveEffectDuration(BaseModel):
    """Structured duration. Either rounds/turns drive in-combat tick, or
    seconds drives narrative-time decay (deferred to
    `[effects-cross-combat]`)."""

    model_config = ConfigDict(extra="forbid")

    rounds: int | None = None
    turns: int | None = None
    seconds: int | None = None
    start_round: int | None = None
    start_turn: int | None = None


class ActiveEffectChange(BaseModel):
    """One mechanical delta. Foundry CONST.ACTIVE_EFFECT_MODES for mode.

    Key vocabulary (Tapestria namespace):
      attack.roll.bonus       — +N or formula on attack rolls
      damage.bonus            — +N or formula on damage rolls
      ac.bonus, ac.override   — AC modifications
      save.<ability>.bonus    — saving-throw bonus (ability lowercase)
      check.<bucket>.bonus    — skill_check / ability_check bonus
      flags.advantage.<bucket>, flags.disadvantage.<bucket>
                              — override-mode boolean adv/disadv

    Value polymorphism: int for scalar `add`/`multiply`; str for dice
    formulas ("1d4", "1d4+2"); bool for advantage flags via `override`.
    """

    model_config = ConfigDict(extra="forbid")

    key: str
    mode: ChangeMode
    value: bool | int | str  # bool first (subclass of int)
    priority: int = 20


class ActiveEffect(BaseModel):
    """Foundry-aligned ActiveEffect document model.

    `id` is the Foundry _id analog (template id, e.g. "effect:bless").
    `origin` collapses prior source_effect_id + source_id into a single
    UUID-style string ("cast:bless:1", "item:sword+1:abc12"). `target_id`
    is the parent Actor analog — combatant id. `statuses` is the set of
    condition slugs the effect imposes (REPLACES the prior
    `bridge_conditions` derivation). `flags` is a free-form dict for
    extensibility; Phase 6 uses {"concentration": bool,
    "applicable_action_types": list[str]} until those fields warrant
    promotion.

    Pure Pydantic model. Zero I/O. Engine-owned during combat;
    Tapestria does not persist instances of this class between combats
    (combat-only scope per spec).
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    origin: str
    target_id: str
    disabled: bool = False
    transfer: bool = False
    duration: ActiveEffectDuration = Field(default_factory=ActiveEffectDuration)
    changes: list[ActiveEffectChange] = Field(default_factory=list)
    statuses: set[str] = Field(default_factory=set)
    flags: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "ActiveEffect",
    "ActiveEffectChange",
    "ActiveEffectDuration",
    "ChangeMode",
]
