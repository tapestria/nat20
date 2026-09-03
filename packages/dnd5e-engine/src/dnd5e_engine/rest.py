"""Library-side standalone rest resolvers — Short Rest, Long Rest, feature recovery.

Public surface for SRD 5.2 rest & recovery, mirroring ``check``'s
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
  it.) Exhaustion reduction is modelled as a pure level input/output (the caller
  passes the creature's current Exhaustion level in, the resolver returns it
  decreased by 1, floored at 0); HP-maximum / ability-score restoration still has no
  producer anywhere in the engine to restore.
"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from dnd5e_engine.activities.dice import roll_expr

# SRD 5.2 rest periods a limited-use resource recharges on. Typed (closed set)
# per the engine's typed-semantics rule.
RecoveryPeriod = Literal["sr", "lr", "dawn", "day", "dusk"]

# Prefix under which the orchestrator namespaces a per-feature "uses spent"
# counter inside the ``custom_counters`` sidecar (``feature_use:<slug>`` →
# ``{"spent": n}``). Kept here so the standalone recovery companion and the
# engine-side cap wiring agree on one key convention.
FEATURE_USE_COUNTER_PREFIX = "feature_use:"

# Prefix under which item charge pools are namespaced inside the same
# ``custom_counters`` sidecar (``item_use:<item-slug>`` → ``{"spent": n}``),
# mirroring ``FEATURE_USE_COUNTER_PREFIX`` for ``Item.uses`` charge tracking.
ITEM_USE_COUNTER_PREFIX = "item_use:"


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
    no dice). ``hp_current`` and ``pool`` are populated by ``resolve_long_rest``
    (the caller reads the post-rest HP and the fully-restored pool from them) and
    left ``None`` by ``resolve_short_rest``, which only mutates the dice pool.

    ``spell_slots`` / ``pact_slots`` are populated only when the matching resolver
    call was handed that pool's ``_max`` (a fresh, fully-restored ``dict``);
    ``exhaustion_level`` is populated only when ``resolve_long_rest`` was handed one
    (the reduced level, floored at 0). Each stays ``None`` when the caller supplied
    no such input — see ``resolve_short_rest`` / ``resolve_long_rest`` for which
    pools each rest type restores.
    """

    healed: int
    dice_spent: int
    dice_remaining: int
    rolls: tuple[int, ...]
    hp_current: int | None = None
    pool: HitDicePool | None = None
    spell_slots: dict[int, int] | None = None
    pact_slots: dict[int, int] | None = None
    exhaustion_level: int | None = None


def _restored_pool(
    current: Mapping[int, int] | None, maximum: Mapping[int, int] | None, *, name: str
) -> dict[int, int] | None:
    """SRD §Long Rest / Pact Magic — a rest restores a pool to its maximum. ``None``
    for both ⇒ ``None`` (caller tracks no such pool); a pool without its maximum is a
    caller bug (``ValueError``) — the resolver never guesses a cap."""
    if maximum is None:
        if current is None:
            return None
        raise ValueError(f"{name} given without {name}_max; the resolver never guesses a maximum")
    return dict(maximum)


def resolve_short_rest(
    pool: HitDicePool,
    dice_to_spend: int,
    con_modifier: int,
    *,
    rng: random.Random,
    pact_slots: Mapping[int, int] | None = None,
    pact_slot_max: Mapping[int, int] | None = None,
) -> RestOutcome:
    """SRD 5.2 §Short Rest — spend ``dice_to_spend`` Hit Point Dice to heal.

    Each spent die heals ``max(1, 1d<hit_die_size> + con_modifier)`` — the 2024
    Foundry-parity per-die floor (the minimum applies to EACH die's own roll+CON,
    never to the summed total). Pure: every draw flows through the passed-in ``rng``.

    Rejects an overspend (``dice_to_spend`` exceeding ``pool.dice_remaining``) and a
    negative spend with ``ValueError``; the resolver never silently clamps.

    Pact Magic — *"You regain all expended Pact Magic spell slots when you finish a
    Short or Long Rest."* — is the ONLY slot pool a Short Rest recovers; pass
    ``pact_slots``/``pact_slot_max`` to restore it (``outcome.pact_slots`` is a fresh
    ``dict`` set to the max). Regular Spellcasting slots are never touched here —
    ``resolve_short_rest`` deliberately takes no ``spell_slots`` parameter.
    """
    if dice_to_spend < 0:
        raise ValueError(f"dice_to_spend must be non-negative, got {dice_to_spend}")
    if dice_to_spend > pool.dice_remaining:
        raise ValueError(
            f"cannot spend {dice_to_spend} Hit Dice; only {pool.dice_remaining} remaining"
        )
    # Validate BEFORE any rng draw: a rejected call must never mutate rng state
    # (determinism — seeded reproducibility is a hard engine promise).
    restored_pact = _restored_pool(pact_slots, pact_slot_max, name="pact_slots")
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
        pact_slots=restored_pact,
    )


def resolve_long_rest(
    pool: HitDicePool,
    hp_current: int,
    hp_max: int,
    *,
    spell_slots: Mapping[int, int] | None = None,
    spell_slot_max: Mapping[int, int] | None = None,
    pact_slots: Mapping[int, int] | None = None,
    pact_slot_max: Mapping[int, int] | None = None,
    exhaustion_level: int | None = None,
) -> RestOutcome:
    """SRD 5.2 §Long Rest — restore ALL HP and ALL spent Hit Point Dice.

    Full recovery per the 2024 ruleset (``content24/``): ``hp_current`` returns to
    ``hp_max`` and the Hit Dice pool refills to ``pool.dice_total`` — NOT the 2014
    half-hit-dice rule. Pure: draws no dice.

    *"Finishing a Long Rest restores any expended spell slots."* — pass
    ``spell_slots``/``spell_slot_max`` (regular Spellcasting) and/or
    ``pact_slots``/``pact_slot_max`` (Pact Magic) to restore either pool; each
    stays ``None`` when its inputs are omitted. *"Exhaustion Reduced. If you have
    the Exhaustion condition, its level decreases by 1."* — pass ``exhaustion_level``
    to get back ``max(0, exhaustion_level - 1)``; omit it (``None``) to leave
    Exhaustion untouched. HP-maximum / ability-score restoration still has no
    producer anywhere in the engine to restore.
    """
    restored_pool = HitDicePool(
        hit_die_size=pool.hit_die_size,
        dice_remaining=pool.dice_total,
        dice_total=pool.dice_total,
    )
    restored_spell = _restored_pool(spell_slots, spell_slot_max, name="spell_slots")
    restored_pact = _restored_pool(pact_slots, pact_slot_max, name="pact_slots")
    reduced_exhaustion = None if exhaustion_level is None else max(0, exhaustion_level - 1)
    return RestOutcome(
        healed=max(0, hp_max - hp_current),
        dice_spent=0,
        dice_remaining=pool.dice_total,
        rolls=(),
        hp_current=hp_max,
        pool=restored_pool,
        spell_slots=restored_spell,
        pact_slots=restored_pact,
        exhaustion_level=reduced_exhaustion,
    )


class _RecoveryRuleView(Protocol):
    """Structural view of a feature's ``uses.recovery[]`` entry.

    The data package's ``dnd5e_srd_data.schema.feature.RecoveryRule`` matches it
    structurally, so a host threads a feature's typed recovery rules straight
    through without this pure module importing the dataset schema.
    """

    @property
    def period(self) -> str: ...
    @property
    def type(self) -> str: ...
    @property
    def formula(self) -> str: ...


def _recover_uses(
    counters: dict[str, dict[str, int]],
    prefix: str,
    period: RecoveryPeriod,
    recovery: Mapping[str, Sequence[_RecoveryRuleView]] | None,
    rng: random.Random | None,
) -> dict[str, int]:
    """Shared core behind ``recover_feature_uses`` and ``recover_item_uses``.

    ``period`` is caller-defined: feature callers pass rest periods (``"sr"``/
    ``"lr"``); item callers may also pass time-of-day periods (``"dawn"``/
    ``"day"``/``"dusk"``), matching Foundry's item ``uses.recovery`` rules.

    ``counters`` is a single entity's ``custom_counters`` mapping (as carried on
    ``_LiveCombat.custom_counters_by_entity[entity_id]``); only keys under
    ``prefix`` (``feature_use:`` or ``item_use:``) are tracked, each with a
    ``{"spent": n}`` shape. Returns ``{"<slug>": <new spent count>, ...}`` for the
    host to write back — pure, it does not mutate ``counters``.

    ``recovery`` maps a slug to its typed ``uses.recovery`` rules (loaded by the
    caller — loader access stays outside this pure module). For each tracked
    counter, the rule whose ``period`` matches the rest's ``period`` decides the
    refill:

    * ``recoverAll`` → the pool fully recharges → ``spent`` returns to ``0``;
    * ``formula`` → regain the formula-many uses → ``spent`` = ``max(0, spent - n)``
      where ``n`` is either the formula parsed as a literal integer (Second
      Wind's Short-Rest ``formula: "1"`` → regain one use) or, when ``rng`` is
      supplied, a dice expression rolled through it (e.g. a wand's ``"1d6 + 1"``
      recharge). Without an ``rng``, a non-literal formula leaves the counter
      unchanged (``spent`` preserved) rather than guessing.

    Period-miss semantics differ by whether recovery data was supplied:

    * ``recovery=None`` (the no-data, backward-compatible path) → every tracked
      counter fully recharges (``spent = 0``) on any rest, matching the original
      signature's behaviour.
    * ``recovery`` supplied but a slug's rules carry NO entry for this rest's
      ``period`` → the counter is UNCHANGED (``spent`` preserved). This is the
      SRD-correct reading: an lr-only feature (Arcane Recovery, Divine
      Intervention — the corpus majority, 41 ``lr`` vs 10 ``sr`` entries) does
      NOT recharge on a Short Rest.
    """
    recovered: dict[str, int] = {}
    for key, counter in counters.items():
        if not key.startswith(prefix):
            continue
        slug = key[len(prefix) :]
        spent = counter.get("spent", 0)
        if recovery is None:
            # No recovery data threaded — pre-existing full-recovery default.
            recovered[slug] = 0
            continue
        rules = recovery.get(slug) or ()
        rule = next((r for r in rules if r.period == period), None)
        if rule is None:
            # Data supplied, no rule for THIS period: the pool does not
            # recharge on this rest (lr-only feature + Short Rest) — preserve.
            recovered[slug] = spent
            continue
        if rule.type == "recoverAll":
            recovered[slug] = 0
            continue
        if rule.type == "formula":
            recovered[slug] = _apply_formula(spent, str(rule.formula), rng)
            continue
        # Unknown recovery type — leave the counter unchanged rather than guess.
        recovered[slug] = spent
    return recovered


def _apply_formula(spent: int, formula: str, rng: random.Random | None) -> int:
    """Regain ``spent`` uses per a ``formula`` recovery rule, floored at zero.

    A literal integer (the SRD feature corpus's only formula shape today) parses
    directly. A non-literal formula rolls as dice through ``rng`` when one is
    supplied (item charge recharges, e.g. ``"1d6 + 1"``); without an ``rng``, or
    if the formula parses as neither a literal nor valid dice, the counter is
    preserved rather than guessed at.
    """
    try:
        regained = int(formula.strip())
    except ValueError:
        if rng is None:
            return spent  # non-literal formula, no dice seam threaded — preserve
        try:
            regained = roll_expr(formula, rng)
        except ValueError:
            return spent  # unparseable even as dice — preserve rather than guess
    return max(0, spent - regained)


def recover_feature_uses(
    counters: dict[str, dict[str, int]],
    period: RecoveryPeriod,
    recovery: Mapping[str, Sequence[_RecoveryRuleView]] | None = None,
    *,
    rng: random.Random | None = None,
) -> dict[str, int]:
    """Apply a rest's feature-use recovery to a caster's ``custom_counters`` sidecar.

    Tracks ``feature_use:<slug>`` keys; see ``_recover_uses`` for the shared
    recovery-rule contract. ``rng``, when supplied, lets a non-literal ``formula``
    rule roll as dice instead of being preserved unchanged.
    """
    return _recover_uses(counters, FEATURE_USE_COUNTER_PREFIX, period, recovery, rng)


def recover_item_uses(
    counters: dict[str, dict[str, int]],
    period: RecoveryPeriod,
    recovery: Mapping[str, Sequence[_RecoveryRuleView]] | None = None,
    *,
    rng: random.Random | None = None,
) -> dict[str, int]:
    """Apply a recharge period to ``item_use:<slug>`` charge pools.

    Same contract as ``recover_feature_uses``; ``recovery`` maps item slug
    → its ``Item.uses.recovery`` rules. Dice formulas ("1d6 + 1", the dominant
    wand recharge) roll through ``rng``; without an rng they preserve the
    counter unchanged.
    """
    return _recover_uses(counters, ITEM_USE_COUNTER_PREFIX, period, recovery, rng)


__all__ = [
    "FEATURE_USE_COUNTER_PREFIX",
    "ITEM_USE_COUNTER_PREFIX",
    "HitDicePool",
    "RecoveryPeriod",
    "RestOutcome",
    "recover_feature_uses",
    "recover_item_uses",
    "resolve_long_rest",
    "resolve_short_rest",
]
