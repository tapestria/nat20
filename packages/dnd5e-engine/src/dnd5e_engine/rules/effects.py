"""Active-effect resolver helpers — Foundry-shaped changes vocabulary.

retires apply_effect_modifiers / derive_applicable_action_types /
derive_condition_scope / filter_stacking / get_bridged_conditions.
Replacements:
  - apply_changes_to_check    folds add-mode and override-mode changes
                              into a check bucket's running total.
  - filter_changes_by_bucket  selects ActiveEffectChange entries whose
                              key matches a target bucket.
  - dedupe_by_identity        dedupes effects by (target_id, id, origin)
                              — the Foundry-shaped identity tuple.

Pure functions, zero I/O.
"""

from __future__ import annotations

import random
from collections.abc import Iterable

from dnd5e_engine.types.effects import ActiveEffect, ActiveEffectChange


def roll_dice_str(expr: str, rng: random.Random | None = None) -> int:
    """Roll a plain ``"NdM"`` / ``"NdM+K"`` / ``"NdM-K"`` expression.

    Pass a seeded ``random.Random`` as ``rng`` for a reproducible result. With
    ``rng=None`` the dice are drawn from the process-global ``random`` module,
    which is only reproducible if the caller seeds it. In-combat rolls never
    come through here — they use the seeded generator threaded from
    ``start_combat(rng_seed=...)``.
    """
    expr = expr.strip()
    if not expr:
        return 0
    sign = 1
    if expr.startswith("-"):
        sign = -1
        expr = expr[1:]
    if "+" in expr:
        dice_part, _, flat = expr.partition("+")
        flat_v = int(flat)
    elif "-" in expr[1:]:
        head = expr[0] if expr[0].isdigit() else ""
        rest = expr[len(head) :]
        dice_part, _, flat = rest.partition("-")
        dice_part = head + dice_part
        flat_v = -int(flat)
    else:
        dice_part = expr
        flat_v = 0
    n_str, _, d_str = dice_part.partition("d")
    n = int(n_str or "1")
    d = int(d_str)
    draw = (rng or random).randint
    total = sum(draw(1, d) for _ in range(n))
    return sign * (total + flat_v)


def filter_changes_by_bucket(
    effects: Iterable[ActiveEffect], bucket: str
) -> list[ActiveEffectChange]:
    """Return changes whose `key == bucket`, preserving order across
    effects then in-effect order."""
    out: list[ActiveEffectChange] = []
    for eff in effects:
        for ch in eff.changes:
            if ch.key == bucket:
                out.append(ch)
    return out


def _numeric_value(value: bool | int | str) -> int | None:
    """Coerce a `multiply`/`upgrade`/`downgrade` change value to an int.

    These three modes are scalar-only per the Foundry core semantics they
    port (`ActiveEffectChange` docstring: "int for scalar `add`/`multiply`");
    unlike `add`, they never carry dice formulas. Returns `None` when a
    string value doesn't parse as a plain integer.
    """
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    try:
        return int(value.strip())
    except ValueError:
        return None


def apply_changes_to_check(
    base_total: int,
    bucket: str,
    effects: Iterable[ActiveEffect],
    rng: random.Random | None = None,
) -> tuple[int, list[str]]:
    """Fold `bucket`-matching `ActiveEffectChange`s into `base_total`.

    Modes:
      - `add` — int, bool, or dice-formula value added to the bucket's
        running contribution (bool/plain-int strings coerce to flat ints;
        strings containing "d" roll as dice formulas).
      - `override` — on a `flags.*` key, surfaces in the breakdown for
        narrator visibility but does not alter the total (advantage/
        disadvantage is a roll-mechanic flag, not a numeric change).
      - `multiply` — multiplies the bucket's accumulated numeric
        contribution SO FAR (not `base_total`, which may include an
        RNG-rolled die — multiplying the whole running total would make
        the result seed-dependent) by `ch.value`.
      - `upgrade` — raises the bucket's accumulated contribution to
        `max(contribution, ch.value)`; never lowers it.
      - `downgrade` — the mirror: `min(contribution, ch.value)`; never
        raises it.
      - `custom` — no Foundry-core semantics to port (Foundry delegates
        `custom` to host-registered callbacks); documented no-op, tracked
        as a Blocked backlog entry.

    Ordering: changes are applied in ascending `ActiveEffectChange.priority`
    order (ties preserve the input order — `sorted` is stable), mirroring
    Foundry's own apply-in-priority-order semantics. This lets a `multiply`
    or `upgrade`/`downgrade` change target contributions from earlier-
    priority `add` changes on the same bucket deterministically, independent
    of the effects' declaration order.

    Returns `(new_total, narrator breakdown lines)`.
    """
    contribution = 0
    breakdown: list[str] = []
    changes = sorted(filter_changes_by_bucket(effects, bucket), key=lambda ch: ch.priority)
    for ch in changes:
        if ch.mode == "add":
            if isinstance(ch.value, str):
                # some SRD asset templates
                # encode flat bonuses as plain integer strings ("1", "-1")
                # rather than dice formulas (Haste / Warding Bond / etc.).
                # Try integer parse first; fall back to the dice parser
                # only when the value contains a 'd'.
                stripped = ch.value.strip()
                if "d" in stripped:
                    rolled = roll_dice_str(ch.value, rng)
                    contribution += rolled
                    breakdown.append(f"effect({ch.value}:{rolled})")
                else:
                    try:
                        flat = int(stripped)
                    except ValueError:
                        breakdown.append(f"effect({ch.value}:unparsed)")
                        continue
                    contribution += flat
                    breakdown.append(f"effect({flat:+d})")
            elif isinstance(ch.value, bool):
                contribution += int(ch.value)
                breakdown.append(f"effect({int(ch.value):+d})")
            else:
                contribution += ch.value
                breakdown.append(f"effect({ch.value:+d})")
        elif ch.mode == "override":
            if ch.key.startswith("flags.advantage."):
                breakdown.append("effect(advantage)")
            elif ch.key.startswith("flags.disadvantage."):
                breakdown.append("effect(disadvantage)")
            else:
                breakdown.append(f"effect({ch.key}=override)")
        elif ch.mode == "multiply":
            factor = _numeric_value(ch.value)
            if factor is None:
                breakdown.append(f"effect({ch.value}:unparsed)")
                continue
            contribution *= factor
            breakdown.append(f"effect(x{factor})")
        elif ch.mode == "upgrade":
            target = _numeric_value(ch.value)
            if target is None:
                breakdown.append(f"effect({ch.value}:unparsed)")
                continue
            contribution = max(contribution, target)
            breakdown.append(f"effect(upgrade:{target})")
        elif ch.mode == "downgrade":
            target = _numeric_value(ch.value)
            if target is None:
                breakdown.append(f"effect({ch.value}:unparsed)")
                continue
            contribution = min(contribution, target)
            breakdown.append(f"effect(downgrade:{target})")
        # custom mode reserved per BACKLOG.md "## Blocked" — no Foundry-core
        # semantics to port (host-callback driven); documented no-op.
    return base_total + contribution, breakdown


def dedupe_by_identity(
    effects: Iterable[ActiveEffect],
) -> list[ActiveEffect]:
    """Dedupe by (target_id, id, origin) — Foundry-shaped identity tuple.
    Keeps the FIRST instance per identity."""
    seen: set[tuple[str, str, str]] = set()
    out: list[ActiveEffect] = []
    for eff in effects:
        key = (eff.target_id, eff.id, eff.origin)
        if key in seen:
            continue
        seen.add(key)
        out.append(eff)
    return out
