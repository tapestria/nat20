from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from dnd5e_srd_data.schema.common import (
    Activity,
    AttackActivity,
    CastActivity,
    CheckActivity,
    DamageActivity,
    EnchantActivity,
    HealActivity,
    SaveActivity,
    SummonActivity,
    TransformActivity,
    UtilityActivity,
)

from .attack import resolve_attack
from .cast import resolve_cast
from .check import resolve_check
from .damage import resolve_damage
from .effects import apply_activity_effects
from .heal import resolve_heal
from .save import resolve_save

if TYPE_CHECKING:
    from dnd5e_srd_data.schema.item import Weapon

    from .context import ActivityResolutionContext

_LOGGER = logging.getLogger(__name__)


def resolve_activity(
    activity: Activity,
    ctx: ActivityResolutionContext,
    *,
    weapon: Weapon | None = None,
) -> None:
    """Route a typed Foundry Activity to its kind handler, emitting CombatEvents.

    The instantaneous kinds ``heal``, ``damage``, ``attack``, ``save`` and
    ``check`` are routed to their handlers. ``isinstance`` checks (not a
    ``activity.kind`` string compare) drive the dispatch so mypy narrows the
    ``Activity`` union to each handler's exact member.

    The ``summon``, ``enchant`` and ``transform`` kinds have no mechanical
    resolution today: they emit no ``CombatEvent`` and log an explicit
    ``activity_kind_narrative`` marker, matching the prior Avrae evaluator's
    narrative passthrough. A ``utility`` activity is the same narrative no-op
    UNLESS it carries effect riders (``effects[]``): the typed Foundry schema
    legitimately hangs "apply a buff" effects on a ``utility`` activity
    (Bless's only activity, Hunter's-Mark's "Mark Creature"), so an
    effects-bearing utility applies those riders per target (Task 9-A FIX 2).
    With all ten union members now routed, the trailing
    ``activity_kind_unhandled`` WARNING is an unreachable defensive guard for a
    malformed (non-``Activity``) input.
    """
    if isinstance(activity, HealActivity):
        return resolve_heal(activity, ctx)
    if isinstance(activity, DamageActivity):
        return resolve_damage(activity, ctx)
    if isinstance(activity, AttackActivity):
        return resolve_attack(activity, ctx, weapon=weapon)
    if isinstance(activity, SaveActivity):
        return resolve_save(activity, ctx)
    if isinstance(activity, CheckActivity):
        return resolve_check(activity, ctx)
    if isinstance(activity, CastActivity):
        return resolve_cast(activity, ctx)
    if isinstance(activity, UtilityActivity) and activity.effects:
        # A utility activity that carries effect riders applies them per target,
        # unconditionally (no attack/save gate). cast_level is derived exactly as
        # the damage/check handlers do.
        cast_level = ctx.slot_level or ctx.base_spell_level or 0
        for target in ctx.targets:
            apply_activity_effects(
                activity, ctx, target, save_succeeded=None, cast_level=cast_level
            )
        return None
    if isinstance(
        activity,
        (SummonActivity, EnchantActivity, TransformActivity, UtilityActivity),
    ):
        _LOGGER.info("activity_kind_narrative kind=%s activity_id=%s", activity.kind, activity.id)
        return None
    _LOGGER.warning("activity_kind_unhandled kind=%s activity_id=%s", activity.kind, activity.id)
    return None
