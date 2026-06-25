"""Library-side standalone check resolver — `resolve_check`.

Public surface for skill checks, ability checks, and saving throws when
no combat handle is required (narrator-time skill prompts, out-of-combat
poison ticks, environmental hazards). Each check honours `active_effects`
passed by the host so Bless / Guidance / Bane land uniformly.

Combat-flow skill checks (`ActionType.SKILL_CHECK` via `dispatch.py`) also
flow through this resolver — see `dispatch._resolve_skill_check`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from dnd5e_engine.rules.effects import apply_changes_to_check
from dnd5e_engine.rules.skills import (
    SKILL_ABILITIES,
    ability_check,
    saving_throw,
    skill_check,
)
from dnd5e_engine.types.effects import ActiveEffect

CheckKind = Literal["skill", "ability", "saving_throw"]


@dataclass(frozen=True)
class CheckSpec:
    """All inputs needed to resolve a standalone check.

    Self-contained: the resolver makes zero I/O calls and reads nothing
    outside the spec. `active_effects` are **pre-filtered by the caller**
    (host-side `effect_store` filters by action type at fetch time via
    EffectRef + D-13). The resolver folds Foundry-shaped
    `ActiveEffectChange` entries whose `key` matches the check's bucket
    (`check.bonus` for skill+ability, `save.bonus` for saving_throw).
    Override-mode changes on `flags.advantage.*` / `flags.disadvantage.*`
    keys surface in `effect_breakdown` for narrator visibility but do NOT
    toggle the roll mechanic — pass `advantage=True` on the spec for that.
    """

    kind: CheckKind
    ability_scores: dict[str, int]
    proficient_skills: tuple[str, ...]
    proficient_saves: tuple[str, ...]
    proficiency_bonus: int

    # `skill` populated when kind == "skill"; ignored otherwise.
    skill: str | None = None
    # `ability` populated when kind in {"ability", "saving_throw"}; for
    # "skill" the ability is derived from SKILL_ABILITIES.
    ability: str | None = None

    dc: int | None = None
    advantage: bool = False
    disadvantage: bool = False
    # Underscore-slug skill names that get ×2 proficiency (already-proficient
    # skills only; skill_check enforces the is_proficient gate). Empty default
    # keeps every existing caller behaviour-neutral until populated downstream.
    expertise_skills: tuple[str, ...] = ()
    active_effects: tuple[ActiveEffect, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CheckResult:
    """Result fragment for a standalone check.

    Fields mirror the existing `SkillOutcome` / `SavingThrowOutcome`
    shapes so host callers can lift this into their EngineResult sub-
    outcomes (host wrap lives in `dispatch._resolve_skill_check` and the
    `app.session.ws_player_action` consult-codex path).
    """

    kind: CheckKind
    skill: str  # empty for ability / saving_throw
    ability: str
    roll_total: int
    modifier: int
    dc: int | None
    success: bool | None
    natural_roll: int
    is_proficient: bool
    # Narrator-facing breakdown strings produced by apply_changes_to_check,
    # e.g. ["effect(1d4:3)", "effect(advantage)"]. Empty when no effects fired.
    effect_breakdown: tuple[str, ...] = field(default_factory=tuple)


# Foundry-shaped `ActiveEffectChange.key` strings. Per D&D 5e, skill
# checks ARE ability checks (with prof bonus). The resolver folds
# changes from BOTH the generic bucket (e.g. `check.bonus`) AND the
# kind-specific bucket (e.g. `check.skill_check.bonus`). This lets the
# common seed templates (Bless, Guidance) ship the generic key while
# more targeted effects (e.g. a Charisma-only save buff via
# `save.charisma.bonus`, or a skill-check-only buff via
# `check.skill_check.bonus`) still land.
_KIND_TO_BUCKETS: dict[CheckKind, tuple[str, ...]] = {
    "skill": ("check.bonus", "check.skill_check.bonus"),
    "ability": ("check.bonus", "check.ability_check.bonus"),
    # save: generic save.bonus, kind-specific save.saving_throw.bonus
    # (for completeness), and the per-ability save.<ability>.bonus
    # synthesized at resolve_check call time below.
    "saving_throw": ("save.bonus", "save.saving_throw.bonus"),
}


def resolve_check(spec: CheckSpec) -> CheckResult:
    """Resolve a standalone skill / ability / saving-throw check.

    Same code path used by `dispatch._resolve_skill_check` for in-combat
    SKILL_CHECK intents. Active effects are pre-filtered by the caller
    (host-side `effect_store` filters by action type at fetch time via
    EffectRef + D-13). The resolver folds Foundry-shaped
    `ActiveEffectChange` entries whose `key` matches the kind's bucket
    (`check.bonus` for skill+ability, `save.bonus` for saving_throw).
    Override-mode changes on `flags.advantage.*` / `flags.disadvantage.*`
    contribute to `effect_breakdown` only; the roll mechanic's advantage
    is set via `spec.advantage`.

    Pure function — zero I/O.
    """
    buckets: tuple[str, ...] = _KIND_TO_BUCKETS[spec.kind]
    # Saving throws additionally honor the per-ability bucket
    # (e.g. `save.wisdom.bonus`) — Cloak of Protection vs. Ring of
    # Mind Shielding semantic.
    if spec.kind == "saving_throw" and spec.ability:
        buckets = (*buckets, f"save.{spec.ability.lower()}.bonus")

    # Codex Phase 6 review iter-10 P2: derive advantage / disadvantage
    # from ``flags.advantage.*`` / ``flags.disadvantage.*`` override
    # changes on active_effects. The ieffect2 translator emits effects
    # like frightened/blinded as flag changes (per-bucket or per-ability),
    # so a frightened actor on a SKILL_CHECK / FLEE should roll at
    # disadvantage. The check kind's relevant flag-bucket roots:
    flag_roots: tuple[str, ...] = ()
    if spec.kind == "skill" or spec.kind == "ability":
        flag_roots = ("flags.advantage.check", "flags.disadvantage.check")
    elif spec.kind == "saving_throw":
        flag_roots = ("flags.advantage.save", "flags.disadvantage.save")
    flag_advantage = False
    flag_disadvantage = False
    # Codex Phase 6 review iter-11 P2: for skill checks, derive the
    # relevant ability from the skill so an ability-tagged
    # ``flags.disadvantage.check.strength`` does not silently penalize a
    # Perception (Wisdom) check. For ability checks the spec carries the
    # ability directly; for saves it's the save ability.
    if spec.kind == "skill" and spec.skill:
        normalized_skill_for_flag = spec.skill.lower().replace(" ", "_")
        ability_suffix = SKILL_ABILITIES.get(normalized_skill_for_flag, "").lower()
    else:
        ability_suffix = (spec.ability or "").lower() if spec.ability else ""
    for eff in spec.active_effects:
        for ch in eff.changes:
            if ch.mode != "override" or ch.value is not True:
                continue
            for root in flag_roots:
                # Accept the broad form ("flags.advantage.check") and the
                # ability-qualified form ("flags.advantage.check.strength"
                # / "flags.advantage.save.wisdom"). Per-ability filter only
                # admits a flag tagged for the active ability (Wisdom save
                # is not disadvantaged by frightened, which targets only
                # checks; a Strength save isn't disadvantaged by a
                # disadvantage tag on Dex saves).
                if ch.key == root:
                    if "advantage" in root and "disadvantage" not in root:
                        flag_advantage = True
                    else:
                        flag_disadvantage = True
                    break
                prefix = f"{root}."
                if ch.key.startswith(prefix) and (
                    not ability_suffix or ch.key[len(prefix) :] == ability_suffix
                ):
                    if "advantage" in root and "disadvantage" not in root:
                        flag_advantage = True
                    else:
                        flag_disadvantage = True
                    break
    effective_advantage = spec.advantage or flag_advantage
    effective_disadvantage = spec.disadvantage or flag_disadvantage

    if spec.kind == "skill":
        if not spec.skill:
            raise ValueError("CheckSpec.kind='skill' requires `skill`")
        base = skill_check(
            skill=spec.skill,
            ability_scores=spec.ability_scores,
            proficient_skills=list(spec.proficient_skills),
            proficiency_bonus=spec.proficiency_bonus,
            dc=spec.dc,
            advantage=effective_advantage,
            disadvantage=effective_disadvantage,
            expertise=spec.skill.lower().replace(" ", "_") in spec.expertise_skills,
        )
        normalized_skill = spec.skill.lower().replace(" ", "_")
        ability_used = SKILL_ABILITIES.get(normalized_skill, "intelligence")
    elif spec.kind == "ability":
        if not spec.ability:
            raise ValueError("CheckSpec.kind='ability' requires `ability`")
        base = ability_check(
            ability=spec.ability,
            ability_scores=spec.ability_scores,
            dc=spec.dc,
            advantage=effective_advantage,
            disadvantage=effective_disadvantage,
        )
        ability_used = spec.ability.lower()
    elif spec.kind == "saving_throw":
        if not spec.ability:
            raise ValueError("CheckSpec.kind='saving_throw' requires `ability`")
        base = saving_throw(
            ability=spec.ability,
            ability_scores=spec.ability_scores,
            proficient_saves=list(spec.proficient_saves),
            proficiency_bonus=spec.proficiency_bonus,
            dc=spec.dc,
            advantage=effective_advantage,
            disadvantage=effective_disadvantage,
        )
        ability_used = spec.ability.lower()
    else:  # pragma: no cover -- exhaustively typed by CheckKind
        raise ValueError(f"unknown CheckKind: {spec.kind!r}")

    # Apply each bucket in order, threading the running total. apply_changes_to_check
    # is additive per call; consecutive calls let multiple bucket keys
    # land on the same check.
    modified_total = base.roll.total
    breakdown: list[str] = []
    for bucket in buckets:
        modified_total, bucket_breakdown = apply_changes_to_check(
            base_total=modified_total,
            bucket=bucket,
            effects=spec.active_effects,
        )
        breakdown.extend(bucket_breakdown)
    success = (modified_total >= spec.dc) if spec.dc is not None else None
    natural_roll = base.roll.dice[0] if base.roll.dice else 0

    return CheckResult(
        kind=spec.kind,
        skill=base.skill,
        ability=ability_used,
        roll_total=modified_total,
        # Invariant: roll_total = natural_roll + modifier. Effect dice
        # contributions are folded into the reported modifier so the
        # `DiceOutcome` contract (`roll_total = die + modifier`) holds
        # downstream. The breakdown of individual effect contributions
        # remains in `effect_breakdown` for narrator visibility.
        modifier=modified_total - natural_roll,
        dc=spec.dc,
        success=success,
        natural_roll=natural_roll,
        is_proficient=base.is_proficient,
        effect_breakdown=tuple(breakdown),
    )


__all__ = [
    "CheckKind",
    "CheckResult",
    "CheckSpec",
    "resolve_check",
]
