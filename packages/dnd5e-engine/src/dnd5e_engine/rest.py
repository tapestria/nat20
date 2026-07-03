"""Library-side standalone rest resolvers — Short Rest, Long Rest, feature recovery.

Public surface for SRD 5.2 rest & recovery, mirroring :mod:`dnd5e_engine.check`'s
standalone / no-combat-handle pattern. A rest has **no** resolvable seam inside a
live combat: ``PlayerIntent.intent_type`` structurally cannot express ``"short_rest"``
(see ``events.py::IntentType``), and SRD 5.2 §Short Rest / §Long Rest list *"Rolling
Initiative"* as one of a rest's own interruptions — a rest occurring inside a combat's
turn loop (which begins with Rolling Initiative) would be definitionally self-
contradicting. Hosts therefore call these pure functions **between** combats.

Purity: zero I/O, zero host imports. Loader access (e.g. resolving a class's
``hit_die`` to ``hit_die_size``) stays with the caller — the resolver reads only the
value-typed inputs it is handed, exactly like ``check.resolve_check``.

SRD 5.2 ground truth (2024 ruleset, ``content24/``):

* §Short Rest — *"For each Hit Point Die you spend in this way, roll the die and add
  your Constitution modifier to it. You regain Hit Points equal to the total (minimum
  of 1 Hit Point)."* Foundry parity (``actor.mjs::rollHitDie``,
  ``max(1, 1d<HD> + @abilities.con.mod)``) floors EACH die's individual roll+CON at 1
  under the 2024 ("modern") ruleset — the floor applies per die, not to the sum.
* §Long Rest — *"Regain All HP. You regain all lost Hit Points and all spent Hit Point
  Dice."* FULL recovery of both. (The 2014 sibling pack in this repo's raw sources
  reads a HALF-hit-dice rule; that edition is NOT what this repo pins — do not encode
  it.) Exhaustion / HP-maximum reduction are out of scope: no producer of a reduced
  HP maximum or ability score exists anywhere in the engine to restore.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Literal

# SRD 5.2 rest periods a limited-use resource recharges on. Typed (closed set)
# per the engine's typed-semantics rule.
RecoveryPeriod = Literal["sr", "lr"]

# Prefix under which the orchestrator namespaces a per-feature "uses spent"
# counter inside the ``custom_counters`` sidecar (``feature_use:<slug>`` →
# ``{"spent": n}``). Kept here so the standalone recovery companion and the
# engine-side cap wiring agree on one key convention.
FEATURE_USE_COUNTER_PREFIX = "feature_use:"


@dataclass(frozen=True)
class HitDicePool:
    """A creature's Hit Point Dice pool at a single die size.

    ``hit_die_size`` is the die's face count (an L5 Fighter's ``d10`` → ``10``,
    sourced by the caller from ``loader.get_class(...).hit_die``). ``dice_remaining``
    are the unspent dice available to spend on a Short Rest; ``dice_total`` is the
    full pool a Long Rest restores to.
    """

    hit_die_size: int
    dice_remaining: int
    dice_total: int


@dataclass(frozen=True)
class RestOutcome:
    """Result fragment for a resolved rest.

    ``healed`` / ``dice_spent`` / ``dice_remaining`` / ``rolls`` describe a Short
    Rest's hit-dice spend (``rolls`` is empty for a Long Rest, whose recovery draws
    no dice). ``hp_current`` and ``pool`` are populated by :func:`resolve_long_rest`
    (the caller reads the post-rest HP and the fully-restored pool from them) and
    left ``None`` by :func:`resolve_short_rest`, which only mutates the dice pool.
    """

    healed: int
    dice_spent: int
    dice_remaining: int
    rolls: tuple[int, ...]
    hp_current: int | None = None
    pool: HitDicePool | None = None


def resolve_short_rest(
    pool: HitDicePool,
    dice_to_spend: int,
    con_modifier: int,
    *,
    rng: random.Random,
) -> RestOutcome:
    """SRD 5.2 §Short Rest — spend ``dice_to_spend`` Hit Point Dice to heal.

    Each spent die heals ``max(1, 1d<hit_die_size> + con_modifier)`` — the 2024
    Foundry-parity per-die floor (the minimum applies to EACH die's own roll+CON,
    never to the summed total). Pure: every draw flows through the passed-in ``rng``.

    Rejects an overspend (``dice_to_spend`` exceeding ``pool.dice_remaining``) and a
    negative spend with :class:`ValueError`; the resolver never silently clamps.
    """
    if dice_to_spend < 0:
        raise ValueError(f"dice_to_spend must be non-negative, got {dice_to_spend}")
    if dice_to_spend > pool.dice_remaining:
        raise ValueError(
            f"cannot spend {dice_to_spend} Hit Dice; only {pool.dice_remaining} remaining"
        )
    rolls = tuple(
        max(1, rng.randint(1, pool.hit_die_size) + con_modifier) for _ in range(dice_to_spend)
    )
    healed = sum(rolls)
    dice_remaining = pool.dice_remaining - dice_to_spend
    return RestOutcome(
        healed=healed,
        dice_spent=dice_to_spend,
        dice_remaining=dice_remaining,
        rolls=rolls,
        pool=HitDicePool(
            hit_die_size=pool.hit_die_size,
            dice_remaining=dice_remaining,
            dice_total=pool.dice_total,
        ),
    )


def resolve_long_rest(pool: HitDicePool, hp_current: int, hp_max: int) -> RestOutcome:
    """SRD 5.2 §Long Rest — restore ALL HP and ALL spent Hit Point Dice.

    Full recovery per the 2024 ruleset (``content24/``): ``hp_current`` returns to
    ``hp_max`` and the Hit Dice pool refills to ``pool.dice_total`` — NOT the 2014
    half-hit-dice rule. HP-maximum reduction / exhaustion are out of scope (no
    producer exists in the engine). Pure: draws no dice.
    """
    restored_pool = HitDicePool(
        hit_die_size=pool.hit_die_size,
        dice_remaining=pool.dice_total,
        dice_total=pool.dice_total,
    )
    return RestOutcome(
        healed=max(0, hp_max - hp_current),
        dice_spent=0,
        dice_remaining=pool.dice_total,
        rolls=(),
        hp_current=hp_max,
        pool=restored_pool,
    )


def recover_feature_uses(
    counters: dict[str, dict[str, int]],
    period: RecoveryPeriod,
) -> dict[str, int]:
    """Apply a rest's feature-use recovery to a caster's ``custom_counters`` sidecar.

    ``counters`` is a single caster's ``custom_counters`` mapping (as carried on
    ``_LiveCombat.custom_counters_by_entity[entity_id]``); the per-feature use cap
    the orchestrator maintains lives under ``feature_use:<slug>`` keys with a
    ``{"spent": n}`` shape. On any rest of the given ``period`` this resets each such
    counter's ``spent`` to 0, returning ``{"<slug>": 0, ...}`` for the host to write
    back (pure — it does not mutate ``counters``).

    The ``dict[str, int]`` sidecar shape cannot itself encode which period a given
    feature recharges on, so this treats every tracked feature-use counter as
    recharging on any (Short **or** Long) rest — correct for Second Wind (recovers on
    both) and every capped feature exercised today. A resource that recharges only on
    a Long Rest would need its recovery data threaded by the caller; ``period`` is
    kept typed and load-bearing for that future differentiation.
    """
    recovered: dict[str, int] = {}
    for key in counters:
        if key.startswith(FEATURE_USE_COUNTER_PREFIX):
            slug = key[len(FEATURE_USE_COUNTER_PREFIX) :]
            recovered[slug] = 0
    return recovered


__all__ = [
    "FEATURE_USE_COUNTER_PREFIX",
    "HitDicePool",
    "RecoveryPeriod",
    "RestOutcome",
    "recover_feature_uses",
    "resolve_long_rest",
    "resolve_short_rest",
]
