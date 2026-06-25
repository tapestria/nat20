"""``damage`` kind handler for the Activity resolver.

A Foundry ``DamageActivity`` (``damage-data.mjs``) applies its damage parts
DIRECTLY to each target — no attack roll, no save. Examples in the canonical
SRD 5.2 corpus: a single Magic Missile dart (``1d4+1`` force), or Divine Smite's
radiant burst (``2d8``/``3d8`` radiant) nested under a melee hit.

Crit rule (``DamageActivityDamageBlock.critical`` is a
:class:`SaveDamageCriticalBlock` — ``{allow, bonus}``): this activity crits ONLY
when ``critical.allow`` is True AND ``ctx.variables["in_crit"]`` is truthy (the
caller sets ``in_crit`` when the activity is nested under a crit attack). On crit
the dice double (``roll_damage_part(crit=True)``) and the parsed ``critical.bonus``
is added ONCE — assigned to the first part's resolved damage type, mirroring
Foundry, where the activity-level crit bonus is extra damage of the activity's
own damage and a damage-kind activity's parts are single-type in the SRD corpus.

Per-part damage TYPE: Foundry stores ``types`` as a list, but a single part
applies as ONE type. Multi-type lists (Chromatic Orb's
``[acid, cold, fire, ...]``) model a player CHOICE of one element, not
simultaneous application. That choice is a player-intent INPUT, read from
``ctx.damage_type_choices`` keyed by activity id; absent a choice the first
listed type is used and the default is logged at INFO (explicit, not a silent
coercion). A typeless part (empty ``types`` — a DATA defect in a handful of
SRD spells; e.g. Call Lightning's 4d10 part) is logged loudly
(``damage_part_untyped``) and skipped: ``apply_damage`` keys strictly by SRD
type and has no untyped bucket, and the resolver cannot invent the SRD-correct
type. Tracked as a ``dnd5e-srd-data`` data bug in ``docs/BACKLOG.md``.

MIRRORS, does not import from, ``effects/damage.py``: @-token resolution runs
through ``formula.resolve_damage_block`` (governing ability = the caster's
spellcasting ability for a spell damage part), and target-side
vuln/resist/immune + the ``DamageApplied`` emission run through ``apply.py``.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import TYPE_CHECKING

from dnd5e_engine.activities.apply import apply_damage
from dnd5e_engine.activities.dice import roll_damage_part, roll_expr
from dnd5e_engine.activities.effects import apply_activity_effects
from dnd5e_engine.activities.formula import resolve_damage_block, resolve_roll_data

if TYPE_CHECKING:
    from dnd5e_srd_data.schema.common import DamageActivity, DamagePartBlock

    from .context import ActivityResolutionContext

_LOGGER = logging.getLogger(__name__)


def resolve_damage(activity: DamageActivity, ctx: ActivityResolutionContext) -> None:
    """Roll ``activity.damage.parts`` ONCE and apply the shared roll to each target.

    SRD area auto-damage rolls its damage ONCE and shares that result across every
    affected target. The parts (and the crit bonus) are therefore rolled BEFORE the
    per-target loop, accumulated into a per-damage-type subtotal, and that single
    ``by_type`` map is handed to ``apply.apply_damage`` for each target (one
    ``DamageApplied`` per type, after THAT target's own vuln/resist/immune). A
    damage-kind activity has no save scaling, so every target takes the same shared
    roll. Crit doubles the dice and adds the parsed ``critical.bonus`` once when
    ``critical.allow`` and ``ctx.variables["in_crit"]`` are both truthy. After a
    target's damage is applied, its effect riders fire (``EffectApplied`` then
    ``ConditionApplied``); a damage activity has no save, so riders apply
    unconditionally per target (``save_succeeded=None``).
    """
    critical = activity.damage.critical
    is_crit = bool(critical.allow) and bool(ctx.variables.get("in_crit"))

    by_type: dict[str, int] = defaultdict(int)
    first_type: str | None = None
    for part in activity.damage.parts:
        damage_type = _part_type(part, activity.id, ctx)
        if damage_type is None:
            continue
        if first_type is None:
            first_type = damage_type
        resolved = resolve_damage_block(part, ctx, ability=ctx.spellcasting_ability)
        by_type[damage_type] += roll_damage_part(
            resolved,
            ctx.rng,
            crit=is_crit,
            character_level=ctx.caster_level,
            slot_level=ctx.slot_level,
            base_level=ctx.base_spell_level,
        )

    if is_crit and critical.bonus and first_type is not None:
        by_type[first_type] += _resolve_critical_bonus(critical.bonus, ctx)

    shared = dict(by_type)
    cast_level = ctx.slot_level or ctx.base_spell_level or 0
    for target in ctx.targets:
        apply_damage(target, shared, ctx)
        apply_activity_effects(activity, ctx, target, save_succeeded=None, cast_level=cast_level)


def _part_type(
    part: DamagePartBlock, activity_id: str, ctx: ActivityResolutionContext
) -> str | None:
    """The single damage type a part applies as.

    * Multi-type list (``[acid, cold, fire, ...]``) models a player CHOICE of one
      element. The choice is a player-intent INPUT, read from
      ``ctx.damage_type_choices[activity_id]`` when present (and validated to be one
      of the offered types). With no choice supplied the FIRST listed type is used
      and the default is logged at INFO — explicit, not a silent coercion. The real
      choice is supplied by player intent at cutover.
    * Empty list: a DATA defect (the SRD part should carry a type). There is no
      untyped bucket in ``apply_damage``, so the part is logged loudly
      (``damage_part_untyped``) and skipped. Tracked as a ``dnd5e-srd-data`` bug
      (see ``docs/BACKLOG.md``); the resolver must not invent the SRD-correct type.
    """
    if not part.types:
        _LOGGER.warning(
            "damage_part_untyped activity_id=%s denomination=%s number=%s",
            activity_id,
            part.denomination,
            part.number,
        )
        return None

    if len(part.types) == 1:
        return part.types[0]

    chosen = ctx.damage_type_choices.get(activity_id)
    if chosen is not None and chosen in part.types:
        return chosen
    if chosen is not None:
        _LOGGER.warning(
            "damage_type_choice_invalid activity_id=%s chose=%s options=%s",
            activity_id,
            chosen,
            part.types,
        )
    _LOGGER.info(
        "damage_type_defaulted activity_id=%s chose=%s options=%s",
        activity_id,
        part.types[0],
        part.types,
    )
    return part.types[0]


def _resolve_critical_bonus(bonus: str, ctx: ActivityResolutionContext) -> int:
    """Resolve @-tokens in ``critical.bonus`` and evaluate it to a flat integer.

    The crit bonus is a flat formula (canonical SRD damage-kind activities ship
    it empty; the resolver handles a token-bearing value defensively). It carries
    no dice in the SRD corpus, so it folds via the same seeded rng for parity
    with ``roll_damage_part`` rather than a separate eval path.
    """
    resolved = resolve_roll_data(bonus, ctx, ability=ctx.spellcasting_ability)
    return roll_expr(resolved, ctx.rng)
