"""Active-effect resolver helpers — Foundry-shaped changes vocabulary.

Phase 6 retires apply_effect_modifiers / derive_applicable_action_types /
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


def roll_dice_str(expr: str) -> int:
    """Roll a "NdM" / "NdM+K" expression. Public test seam: callers
    monkeypatch this symbol (or `random.randint`) for determinism in tests."""
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
        rest = expr[len(head):]
        dice_part, _, flat = rest.partition("-")
        dice_part = head + dice_part
        flat_v = -int(flat)
    else:
        dice_part = expr
        flat_v = 0
    n_str, _, d_str = dice_part.partition("d")
    n = int(n_str or "1")
    d = int(d_str)
    total = sum(random.randint(1, d) for _ in range(n))
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


def apply_changes_to_check(
    base_total: int,
    bucket: str,
    effects: Iterable[ActiveEffect],
) -> tuple[int, list[str]]:
    """Fold mode=add (int or formula) changes for `bucket` into
    base_total. Mode=override on a `flags.*` key contributes to the
    breakdown but does not alter the total. Returns (new_total, narrator
    breakdown lines).
    """
    total = base_total
    breakdown: list[str] = []
    for ch in filter_changes_by_bucket(effects, bucket):
        if ch.mode == "add":
            if isinstance(ch.value, str):
                # Codex Phase 6 review iter-11 P1: some SRD asset templates
                # encode flat bonuses as plain integer strings ("1", "-1")
                # rather than dice formulas (Haste / Warding Bond / etc.).
                # Try integer parse first; fall back to the dice parser
                # only when the value contains a 'd'.
                stripped = ch.value.strip()
                if "d" in stripped:
                    rolled = roll_dice_str(ch.value)
                    total += rolled
                    breakdown.append(f"effect({ch.value}:{rolled})")
                else:
                    try:
                        flat = int(stripped)
                    except ValueError:
                        breakdown.append(f"effect({ch.value}:unparsed)")
                        continue
                    total += flat
                    breakdown.append(f"effect({flat:+d})")
            elif isinstance(ch.value, bool):
                total += int(ch.value)
                breakdown.append(f"effect({int(ch.value):+d})")
            else:
                total += ch.value
                breakdown.append(f"effect({ch.value:+d})")
        elif ch.mode == "override":
            if ch.key.startswith("flags.advantage."):
                breakdown.append("effect(advantage)")
            elif ch.key.startswith("flags.disadvantage."):
                breakdown.append("effect(disadvantage)")
            else:
                breakdown.append(f"effect({ch.key}=override)")
        # custom / multiply / downgrade / upgrade reserved per
        # [foundry-extended-changes-modes] backlog; ignored in Phase 6.
    return total, breakdown


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
