"""PassiveEffect (lib definition) → ActiveEffect (runtime) builder.

The typed lib ships ``PassiveEffect`` — the effect *definition* riding on a
spell/item (``changes`` / ``statuses`` / ``duration``). The resolver emits the
engine's ``ActiveEffect`` (the runtime effect carried by ``EffectApplied``).
This module is the one translation seam between the two.

``ActiveEffectChange.mode`` is a string Literal (``ChangeMode``); the lib's
``PassiveEffectChange.mode`` is the Foundry ``CONST.ACTIVE_EFFECT_MODES`` int.
``_MODE_MAP`` is the single source of truth for that int→str correspondence;
its values are pinned to the ``ChangeMode`` Literal order (index == int key).

The ``id``/``origin`` slug conventions MIRROR ``effects/ieffect2.py``
(``_effect_id_from_name`` / ``_origin_from_name``) verbatim — the orchestrator
parses ``origin`` back into ``cast:<slug>:<caster_id>`` in Piece 3, so any drift
here breaks that round-trip.
"""

from __future__ import annotations

import logging
import typing
from typing import TYPE_CHECKING, get_args

from dnd5e_engine.activities.formula import resolve_roll_data
from dnd5e_engine.events import ConditionApplied, ConditionType, EffectApplied
from dnd5e_engine.types.combat import Combatant
from dnd5e_engine.types.effects import (
    ActiveEffect,
    ActiveEffectChange,
    ActiveEffectDuration,
    ChangeMode,
)

if TYPE_CHECKING:
    from dnd5e_srd_data.schema.common import (
        PassiveEffect,
        PassiveEffectChange,
        _ActivityBaseWithEffects,
    )

    from .context import ActivityResolutionContext

_LOGGER = logging.getLogger(__name__)

# The valid SRD condition ids — a status string becomes a ConditionApplied only
# when it names one of these. Derived from the ConditionType Literal so the two
# never drift.
_CONDITION_VALUES: frozenset[str] = frozenset(get_args(ConditionType))

# Foundry CONST.ACTIVE_EFFECT_MODES → ChangeMode Literal. Pinned to the Literal
# member order in types/effects.py (index == int key); test_effects_builder
# asserts the two stay in lockstep.
_MODE_MAP: dict[int, ChangeMode] = {
    0: "custom",
    1: "multiply",
    2: "add",
    3: "downgrade",
    4: "upgrade",
    5: "override",
}

_DEFAULT_CHANGE_PRIORITY = 20


def _name_slug(name: str) -> str:
    return name.lower().replace(" ", "_")


def _effect_id_from_name(name: str) -> str:
    """Synthesize an ActiveEffect.id from the effect name (mirrors ieffect2)."""
    return f"effect:{_name_slug(name)}"


def _origin_from_name(name: str, caster_id: str) -> str:
    """Synthesize an ActiveEffect.origin from name + caster (mirrors ieffect2)."""
    return f"cast:{_name_slug(name)}:{caster_id}"


def _passive_change_to_active(
    ch: PassiveEffectChange, ctx: ActivityResolutionContext | None
) -> ActiveEffectChange:
    """Translate one lib ``PassiveEffectChange`` to an ``ActiveEffectChange``.

    ``mode`` int→str via ``_MODE_MAP``; an out-of-range int defaults to
    ``"custom"`` and logs loudly. ``priority`` defaults to 20 when the source
    leaves it ``None``.

    ``value`` stays the Foundry string EXCEPT for level-scaled roll-data tokens
    (``@scale.*`` / ``@classes.*``): Rage's ``system.bonuses.mwak.damage`` ships
    ``"+@scale.barbarian.rage-damage"``, which must be the CONCRETE bonus
    (``"+2"`` at L5) the moment the effect lands so the next attack's hydration
    fold reads a real number, not an unresolved token. When ``ctx`` is supplied
    and the value carries an ``@``-token, it is resolved here at apply-time via
    the same pure formula layer the dice/heal paths use.
    """
    mode = _MODE_MAP.get(ch.mode)
    if mode is None:
        _LOGGER.warning(
            "effect_change_mode_unknown mode=%s key=%s value=%s — defaulting to custom",
            ch.mode,
            ch.key,
            ch.value,
        )
        mode = "custom"
    priority = ch.priority if ch.priority is not None else _DEFAULT_CHANGE_PRIORITY
    value = ch.value
    if ctx is not None and isinstance(value, str) and "@" in value:
        # Resolve @scale.*/@classes.* (and any other roll-data token) against the
        # caster's pre-resolved carriers. No governing ability is supplied —
        # feature passive-effect change values never carry a bare ``@mod``.
        value = resolve_roll_data(value, ctx)
    return ActiveEffectChange(key=ch.key, mode=mode, value=value, priority=priority)


def _duration_from_passive(duration: dict[str, typing.Any] | None) -> ActiveEffectDuration:
    """Map the lib's free-form duration dict to the structured runtime duration.

    Only ``rounds`` / ``turns`` / ``seconds`` are carried; absent keys (and a
    ``None``/empty dict) leave the corresponding field ``None``.
    """
    if not duration:
        return ActiveEffectDuration()
    return ActiveEffectDuration(
        rounds=duration.get("rounds"),
        turns=duration.get("turns"),
        seconds=duration.get("seconds"),
    )


def passive_effect_to_active_effect(
    pe: PassiveEffect,
    *,
    target_id: str,
    caster_id: str,
    concentration: bool = False,
    ctx: ActivityResolutionContext | None = None,
) -> ActiveEffect:
    """Build the runtime ``ActiveEffect`` the resolver emits for one target.

    ``id``/``origin`` follow the ieffect2 slug conventions so the orchestrator
    can parse them back in Piece 3. ``flags`` carries ``{"concentration": True}``
    only when the caster's cast is concentration-gated; otherwise empty.

    ``ctx`` (when supplied) resolves level-scaled roll-data tokens in each
    change value at apply-time (Rage's ``@scale.barbarian.rage-damage`` → the
    concrete ``+2``); absent, change values stay verbatim Foundry strings.
    """
    return ActiveEffect(
        id=_effect_id_from_name(pe.name),
        name=pe.name,
        origin=_origin_from_name(pe.name, caster_id),
        target_id=target_id,
        disabled=pe.disabled,
        transfer=pe.transfer,
        duration=_duration_from_passive(pe.duration),
        changes=[_passive_change_to_active(ch, ctx) for ch in pe.changes],
        statuses=set(pe.statuses),
        flags={"concentration": True} if concentration else {},
    )


def apply_activity_effects(
    activity: _ActivityBaseWithEffects,
    ctx: ActivityResolutionContext,
    target: Combatant,
    *,
    save_succeeded: bool | None,
    cast_level: int,
) -> None:
    """Apply an activity's effect riders to ``target``, emitting events.

    Each ``AppliedEffectRef`` on the activity points (by ``ref.id``) at a
    ``PassiveEffect`` definition the parent entity carries (``ctx.source_passive_
    effects``). For every ref that resolves and passes the level + on_save gates,
    one ``EffectApplied`` is emitted (the translated runtime ``ActiveEffect``),
    followed by one ``ConditionApplied`` per status that names a valid SRD
    condition.

    The EffectApplied-then-ConditionApplied emit order is load-bearing: the
    orchestrator (Piece 3) pairs each condition to its effect by emit order.

    ``save_succeeded`` is the target's save outcome for save activities (``None``
    for non-save kinds, which apply unconditionally). ``cast_level`` is the slot
    level the activity was cast at, gated against each ref's ``level`` block.

    Mirrors (does not import) ``effects/ieffect2._apply_effect``'s emit shape.
    """
    by_id: dict[str, PassiveEffect] = {pe.id: pe for pe in ctx.source_passive_effects}

    for ref in activity.effects:
        pe = by_id.get(ref.id)
        if pe is None:
            _LOGGER.warning(
                "effect_ref_unresolved ref_id=%s activity=%s",
                ref.id,
                activity.id,
            )
            continue

        # Level gate: the ref applies only within [min, max] (either may be
        # unset). cast_level outside the band → this ref doesn't fire at this
        # slot level.
        if ref.level.min is not None and cast_level < ref.level.min:
            continue
        if ref.level.max is not None and cast_level > ref.level.max:
            continue

        # On-save gate (save activities only). Foundry per-effect semantics:
        # on_save=True applies even on a successful save; False/None applies
        # only on a FAILED save. Non-save activities (save_succeeded is None)
        # apply unconditionally.
        if save_succeeded is True and not ref.on_save:
            continue

        ae = passive_effect_to_active_effect(
            pe,
            target_id=target.entity_id,
            caster_id=ctx.caster.entity_id,
            concentration=ctx.concentration,
            ctx=ctx,
        )
        ctx.event_emitter(EffectApplied(effect=ae))

        # Conditions land AFTER the EffectApplied (load-bearing order), in a
        # deterministic (sorted) sequence. A status that isn't a valid SRD
        # ConditionType still rides on ae.statuses; only ConditionApplied is
        # gated on the mapping.
        for status in sorted(pe.statuses):
            if status in _CONDITION_VALUES:
                ctx.event_emitter(
                    ConditionApplied(
                        target_id=target.entity_id,
                        condition=typing.cast("ConditionType", status),
                    )
                )
            else:
                _LOGGER.info("effect_status_unmapped status=%s", status)
