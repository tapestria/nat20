"""The single saving-throw primitive shared by the ``save`` kind and weapon mastery.

A saving throw is one concept: short-circuit to failure if the target auto-fails
this ability (``ctx.passive_save_auto_fail`` — no d20 drawn), else roll a natural
d20 (honoring the ``force_save_d20`` test seam for the first target only, plus
target-side advantage/disadvantage from ``ctx.passive_save_adv`` /
``passive_save_dis``), add the target's RESOLVED per-ability save modifier off
``ctx.passive_save_modifiers`` and the rolled ``ctx.passive_save_bonus`` dice
(Bless/Bane), and compare ``total >= dc``. Both ``activities/save.py`` (per-target
loop) and ``activities/mastery.py`` (a single topple Con save) used to
re-implement this independently; this module owns it once.

The caller still constructs and emits ``SaveRolled`` because the two sites carry
different surrounding context — ``save.py`` emits per target inside its loop with
the activity's save ability, while ``mastery.py`` emits a single ``con`` save
before applying ``prone``. The shared piece is the ROLL + MODIFIER + COMPARISON,
not the event shape, so the primitive returns a ``SaveRoll`` envelope (total,
success, kept natural, flat modifier, advantage sources) and the caller decides
what event to emit.

MIRRORS, does not import from, ``effects/save.py``:

* the natural d20 honors ``ctx.variables["force_save_d20"]`` for the FIRST target
  (``target_index == 0``) only — every other target rolls live off ``ctx.rng`` so
  a forced value never silently reuses one kept d20 across a multi-target save.
* the target modifier is the RESOLVED per-ability integer off the per-target
  sidecar (``ctx.passive_save_modifiers[entity_id][ability]``), NOT rebuilt from
  ability score + proficiency; an absent target / ability contributes +0.
* auto-fail / advantage / disadvantage / save-bonus are sourced from the same
  per-target sidecar shape the OLD the legacy evaluator path read off the host effect store; empty
  sidecars reproduce the prior single-d20 + per-ability-mod behavior exactly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import d20

from dnd5e_engine.activities.d20 import AdvantageSources, D20Result, roll_d20_test
from dnd5e_engine.events import AdvantageMode, AdvantageSource
from dnd5e_engine.spatial import cover_bonus

if TYPE_CHECKING:
    from dnd5e_engine.types.combat import Combatant

    from .context import ActivityResolutionContext

# Test-determinism seam for the natural save d20 (our own code; effects/save.py
# has none and relies on a seeded ctx.rng). Scoped to the first target.
FORCE_SAVE_D20: Final = "force_save_d20"


@dataclass(frozen=True)
class SaveRoll:
    """The resolved outcome of one saving throw, with its D20 Test provenance.

    A named envelope rather than a bare tuple (CLAUDE.md: results are named
    envelopes) because the callers now forward the roll breakdown onto
    ``SaveRolled``.

    * ``natural`` is the KEPT die (post advantage/disadvantage), or ``None``
      when the save auto-failed and no die was drawn.
    * ``modifier`` is the FLAT, deterministic part of the total — the resolved
      per-ability save modifier plus any Dexterity cover bonus. It EXCLUDES the
      ``passive_save_bonus`` dice (SRD §Bless / §Bane), which must be rolled
      AFTER the d20 to keep the seeded draw ORDER intact; mirrors the
      ``AttackRolled.modifier`` convention. So ``total == natural + modifier``
      holds only when no Bless/Bane-style sidecar is active on the target.
    * ``mode`` is the resolved SRD 5.2 D20 Test mode (advantage and
      disadvantage cancel to ``"normal"``); an auto-failed save reports
      ``"normal"`` since no die was rolled.
    * ``sources`` is the advantage/disadvantage provenance actually applied.
    """

    total: int
    succeeded: bool
    natural: int | None
    modifier: int
    mode: AdvantageMode
    sources: tuple[AdvantageSource, ...]


def roll_save(
    ctx: ActivityResolutionContext,
    target: Combatant,
    ability: str,
    dc: int,
    *,
    target_index: int = 0,
) -> SaveRoll:
    """Roll ``target``'s ``ability`` save vs ``dc``; return the ``SaveRoll`` envelope.

    Mirrors the full target-side save sidecar the OLD the legacy evaluator path
    (``effects/save.py``) consumed:

    * ``ctx.passive_save_auto_fail[id]`` — if ``ability`` (upper-case) is listed
      (Paralyzed / Stunned / Petrified / Unconscious auto-fail STR + DEX), the
      save short-circuits to a failed ``SaveRoll`` with NO d20 draw, so the
      deterministic rng stream is not perturbed (matches ``conditions.py`` +
      ``effects/save.py:_is_auto_fail``).
    * ``ctx.passive_save_adv[id]`` / ``ctx.passive_save_dis[id]`` — advantage /
      disadvantage on the d20, fed to the shared ``roll_d20_test`` primitive
      (F2c); an ability present in both cancels to normal (SRD 5.2 §Advantage
      and Disadvantage, the legacy evaluator ``reconcile_adv``).
    * ``ctx.passive_save_modifiers[id][ability]`` — the resolved per-ability
      integer modifier (absent → +0).
    * ``ctx.passive_save_bonus[id]`` — a signed dice-expression string (Bless
      ``"+1d4"`` / Bane ``"-1d4"``), rolled through ``ctx.rng`` (absent → +0).
    * ``ctx.target_cover[id]`` — SRD 5.2 §Cover: half (+2) / three-quarters
      (+5) cover adds directly to a **Dexterity** save's total (a bonus to
      the covered creature's OWN roll, not a DC adjustment — "a bonus to AC
      AND Dexterity saving throws"). Inert for any other ability.

    The natural d20 honors ``ctx.variables["force_save_d20"]`` for the first
    target (``target_index == 0``) only. Success is ``total >= dc``. The caller
    emits ``SaveRolled`` (the event field set differs per call site). Empty
    sidecars reproduce the prior single-d20 + per-ability-mod behavior exactly.
    """
    if _is_auto_fail(ctx, target, ability):
        return SaveRoll(
            total=0, succeeded=False, natural=None, modifier=0, mode="normal", sources=()
        )
    modifier = _target_save_modifier(ctx, target, ability)
    if ability == "dex":
        modifier += cover_bonus(ctx.target_cover.get(target.entity_id, "none"))
    # Draw ORDER matters for determinism: the d20 first, the Bless/Bane bonus
    # dice after (folding those dice into the primitive's flat modifier would
    # mean rolling them BEFORE the d20 and would shift the seeded stream).
    roll = _roll_save_d20(ctx, target, ability, modifier, target_index=target_index)
    total = roll.total + _passive_save_bonus(ctx, target)
    return SaveRoll(
        total=total,
        succeeded=total >= dc,
        natural=roll.kept,
        modifier=roll.modifier,
        mode=roll.mode,
        sources=roll.sources,
    )


def _is_auto_fail(ctx: ActivityResolutionContext, target: Combatant, ability: str) -> bool:
    """True when ``target`` auto-fails the ``ability`` save (no d20).

    SRD §Conditions: Paralyzed / Stunned / Petrified / Unconscious creatures
    auto-fail STR + DEX saves. The sidecar lists ability codes UPPER-case
    (``conditions.py``); normalize the activity's lower-case ability to match.
    """
    auto_fail = ctx.passive_save_auto_fail.get(target.entity_id, [])
    return ability.upper() in auto_fail


def _roll_save_d20(
    ctx: ActivityResolutionContext,
    target: Combatant,
    ability: str,
    modifier: int,
    *,
    target_index: int,
) -> D20Result:
    """The save's D20 Test, honoring ``variables["force_save_d20"]`` + adv/dis.

    Delegates to the shared ``activities/d20.py::roll_d20_test`` primitive (F2c)
    so every d20 in the engine resolves advantage in ONE place. ``modifier`` is
    the flat, deterministic part of the save total (see ``SaveRoll.modifier``).

    Draw discipline is unchanged by the delegation: normal mode consumes exactly
    one ``rng.randint(1, 20)``, advantage/disadvantage exactly two, a forced
    value zero.

    The forced value is a TEST seam scoped to the FIRST target only
    (``target_index == 0``), mirroring ``activities/attack.py``'s ``force_d20``
    discipline: every other target rolls live off ``ctx.rng`` so a forced value
    never silently reuses one kept d20 across a multi-target save. A forced value
    bypasses adv/dis (the test pins the kept natural directly).

    Advantage / disadvantage are sourced from ``ctx.passive_save_adv`` /
    ``ctx.passive_save_dis`` (UPPER-case ability codes); an ability present in
    both cancels to normal (SRD 5.2 §Advantage and Disadvantage — the primitive
    owns that reconciliation now). Both sidecars are typed as the
    ``"condition:target"`` ``AdvantageSource``: their sole in-engine producer is
    ``rules/conditions.py::project_passive_save_modifiers`` (SRD §Conditions —
    Restrained ⇒ disadvantage on DEX saves, and so on), i.e. always a condition
    on the SAVING creature. ``_fold_active_effect_changes`` never writes these
    keys, so an ``"effect"`` tag would be wrong for every entry the engine
    itself hydrates. A host hand-building the sidecar from a non-condition
    source is the only way to make the tag inexact.
    """
    forced = ctx.variables.get(FORCE_SAVE_D20)
    forced_natural = int(forced) if forced is not None and target_index == 0 else None

    ability_upper = ability.upper()
    has_adv = ability_upper in ctx.passive_save_adv.get(target.entity_id, [])
    has_dis = ability_upper in ctx.passive_save_dis.get(target.entity_id, [])
    sources = AdvantageSources(
        advantage=("condition:target",) if has_adv else (),
        disadvantage=("condition:target",) if has_dis else (),
    )
    return roll_d20_test(ctx.rng, modifier, sources, forced_natural=forced_natural)


def _passive_save_bonus(ctx: ActivityResolutionContext, target: Combatant) -> int:
    """Roll ``target``'s ``passive_save_bonus`` dice expression (Bless/Bane).

    Mirrors ``effects/save.py:_roll_passive_save_bonus``: the sidecar carries a
    signed dice-expression string (``"+1d4"`` Bless, ``"-1d4"`` Bane; stacked
    sources pre-joined as ``"a + b"``). Evaluated through ``ctx.rng`` so the
    bonus dice land in the same seed stream as the save d20. Absent / empty → +0.
    """
    expr = ctx.passive_save_bonus.get(target.entity_id)
    if not expr:
        return 0
    try:
        ast = d20.parse(expr)
    except d20.RollError as exc:
        raise ValueError(
            f"Unparseable passive_save_bonus dice expression {expr!r}; the "
            "orchestrator hydration must emit a d20-parseable signed expression "
            "(e.g. '-1d4' for Bane, '+1d4' for Bless)."
        ) from exc
    return _eval_node(ast.roll, ctx)


def _eval_node(node: d20.ast.Node, ctx: ActivityResolutionContext) -> int:
    """Evaluate a parsed ``d20`` AST against ``ctx.rng`` (deterministic seed).

    Mirrors ``effects/save.py:_eval_node`` — ``d20.roll`` uses the global RNG;
    walking the AST and drawing each die face via ``ctx.rng`` keeps the bonus in
    the seeded stream. Supports the literal / dice / unary / binary / parenthetical
    node set the signed bonus expressions exercise.
    """
    if isinstance(node, d20.ast.Literal):
        return int(node.value)
    if isinstance(node, d20.ast.Dice):
        return sum(ctx.rng.randint(1, int(node.size)) for _ in range(int(node.num)))
    if isinstance(node, d20.ast.UnOp):
        inner = _eval_node(node.value, ctx)
        if node.op == "+":
            return inner
        if node.op == "-":
            return -inner
        raise ValueError(f"Unsupported unary op in passive_save_bonus: {node.op!r}")
    if isinstance(node, d20.ast.BinOp):
        left = _eval_node(node.left, ctx)
        right = _eval_node(node.right, ctx)
        if node.op == "+":
            return left + right
        if node.op == "-":
            return left - right
        raise ValueError(f"Unsupported binary op in passive_save_bonus: {node.op!r}")
    if isinstance(node, d20.ast.Parenthetical):
        return _eval_node(node.value, ctx)
    raise ValueError(f"Unsupported node in passive_save_bonus: {type(node).__name__}")


def _target_save_modifier(ctx: ActivityResolutionContext, target: Combatant, ability: str) -> int:
    """The target's resolved save modifier for ``ability``.

    Mirrors ``effects/save.py:_read_save_modifier`` — read the RESOLVED per-
    ability integer off the per-target sidecar, never rebuilt from ability score
    + proficiency. ``Combatant`` carries no per-ability save table, so the value
    comes from ``ctx.passive_save_modifiers[entity_id][ability]``; an absent
    target or ability contributes +0 (the same 0 fallback the effects path uses).
    """
    return ctx.passive_save_modifiers.get(target.entity_id, {}).get(ability, 0)
