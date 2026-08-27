"""D&D 5e Active Effects — Foundry VTT dnd5e-aligned schema.

of the dnd5e-engine extraction: the prior `effect_id` /
`source_entity_id` / `rounds_remaining` / `modifiers: list[EffectModifier]`
shape is replaced by the Foundry-aligned model. `EffectModifier` and
`EffectRef` retire.

Reference: /tmp/foundry-dnd5e/module/documents/active-effect.mjs and
/tmp/foundry-dnd5e/module/data/active-effect/. Foundry's structural
choices (statuses-set replaces bridge-conditions, structured duration,
changes[] with mode/value/priority, origin UUID) carry over verbatim
where applicable. The `changes[].key` vocabulary uses a host's flat
namespace ("attack.roll.bonus", "save.wisdom.bonus",
"flags.advantage.<bucket>"), not Foundry's Actor-data dotted paths.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ChangeMode = Literal["custom", "multiply", "add", "downgrade", "upgrade", "override"]


class ActiveEffectDuration(BaseModel):
    """Structured duration. All three counters tick in combat (F3b).

    SRD 5.2 §Duration puts a round at about 6 seconds, so the engine reads the
    three fields as follows (``orchestrator._tick_durations_at_turn_end`` for
    ``rounds``, ``orchestrator._expire_timed_effects_at_turn_end`` for the
    rest; both are ``turn_end`` hooks on ``turn_lifecycle``):

    ``rounds``
        Decremented once per round at the **caster's** turn end (parsed from
        the effect ``origin``; item/environment origins fall back to the
        target's turn end). Reaching zero emits
        ``EffectExpired(reason="duration")``.
    ``turns``
        Decremented at the **target's own** turn end — durations counted in
        the subject's turns rather than the caster's. Independent of
        ``rounds``: whichever counter hits zero first expires the effect.
    ``seconds``
        Narrative-time duration, read in combat as ``ceil(seconds / 6)``
        rounds and ticked exactly like ``rounds`` (caster-keyed). The derived
        count is materialised once into ``rounds`` (and decremented in the
        same pass, so ``seconds=12`` is indistinguishable from ``rounds=2``);
        ``seconds`` itself is never mutated. **If an effect carries both
        ``rounds`` and ``seconds``, ``rounds`` wins** — the seconds branch only
        fires when ``rounds is None``. Foundry packs routinely ship both
        (Bless: ``rounds=10, seconds=60``).

    ``start_round`` / ``start_turn`` are carried for host bookkeeping and are
    not read by the engine. Concentration-flagged effects are exempt from
    every branch above: the concentration cascade and the per-turn repeat save
    own their lifetime, and the packs' counters on them are display-only
    (Hunter's Mark ships ``seconds=600``).
    """

    model_config = ConfigDict(extra="forbid")

    rounds: int | None = None
    turns: int | None = None
    seconds: int | None = None
    start_round: int | None = None
    start_turn: int | None = None


class ActiveEffectChange(BaseModel):
    """One mechanical delta. Foundry CONST.ACTIVE_EFFECT_MODES for mode.

    Key vocabulary (the host namespace):
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
    extensibility; uses {"concentration": bool,
    "applicable_action_types": list[str]} until those fields warrant
    promotion. One flag is a duration, not a modifier:
    ``{"until_end_of_next_turn_of": "<entity_id>"}`` expresses SRD's "until
    the end of your next turn" — the engine expires the effect at that
    actor's next turn end, granting a one-turn grace when the effect was
    applied during that actor's own turn.

    Pure Pydantic model. Zero I/O. Engine-owned during combat;
    the host does not persist instances of this class between combats
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
