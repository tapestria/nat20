"""Cross-generation parity: the two attack-roll implementations must agree.

The engine ships two undeclared generations of the attack roll (see
``BACKLOG.md`` § "Architecture (2026-08-22)"):

* Gen 1 — ``rules/combat.py::attack_roll`` / ``resolve_player_attack``, live in
  hosts via ``dispatch.resolve_combat_action``. Draws from the process-global
  ``random`` module.
* Gen 2 — ``activities/attack.py::_roll_natural_d20`` / ``_resolve_hit_outcome``
  / ``resolve_attack``, driven by the seeded ``ActivityResolutionContext.rng``.

Every SRD rules fix must land at both sites until the generations are
reconciled. PR #11 fixed a crit-on-the-discarded-die bug that existed ONLY in
Gen 1 — Gen 2 never had it. This module is the test that would have caught that
drift: it feeds both generations the same d20 stream (``random.seed(s)`` and
``random.Random(s)`` are the same Mersenne Twister sequence) and asserts the
kept natural die and the hit / crit / miss classification are identical.

Scope note: Gen 2's live ``resolve_attack`` path always rolls ``mode="normal"``
(rolling the base attack with advantage/disadvantage is a deferred delta —
see ``BACKLOG.md``), so advantage / disadvantage parity is pinned at the
primitive seam (``_roll_natural_d20`` + ``_resolve_hit_outcome``), and the
end-to-end pass through both public entry points covers the flat roll.
"""

from __future__ import annotations

import random
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from dnd5e_srd_data.loader import BundledAssetLoader
from dnd5e_srd_data.schema.common import AttackActivity
from dnd5e_srd_data.schema.item import Weapon

from dnd5e_engine.activities.attack import _resolve_hit_outcome, _roll_natural_d20
from dnd5e_engine.activities.context import ActivityResolutionContext
from dnd5e_engine.activities.resolver import resolve_activity
from dnd5e_engine.events import AttackRolled, CombatEvent
from dnd5e_engine.rules.combat import HitType, attack_roll, resolve_player_attack
from dnd5e_engine.types.combat import Combatant

SEEDS = range(64)
ATTACK_BONUS = 5  # str 16 (+3) + proficiency (+2) — matches the longsword build below
TARGET_AC = 15


@contextmanager
def _global_random_seeded(seed: int) -> Iterator[None]:
    """Seed the process-global ``random`` for Gen 1, restoring state afterwards."""
    state = random.getstate()
    random.seed(seed)
    try:
        yield
    finally:
        random.setstate(state)


def _combatant(entity_id: str, *, ac: int = 10, strength: int = 10) -> Combatant:
    kind = "Character" if entity_id.startswith("char:") else "Monster"
    return Combatant(
        entity_id=entity_id,
        entity_type=kind,
        name=entity_id,
        initiative=10,
        hp_current=500,
        hp_max=500,
        ac=ac,
        strength=strength,
    )


def _ctx(
    seed: int, events: list[CombatEvent] | None = None, *, target_ac: int = TARGET_AC
) -> ActivityResolutionContext:
    return ActivityResolutionContext(
        rng=random.Random(seed),
        caster=_combatant("char:hero", strength=16),
        targets=[_combatant("mon:foe", ac=target_ac)],
        event_emitter=(events.append if events is not None else (lambda ev: None)),
        caster_abilities={"str": 16, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10},
        caster_proficiency_bonus=2,
        caster_level=1,
    )


@pytest.fixture(scope="module")
def longsword() -> Weapon:
    weapon = BundledAssetLoader().get_weapon("longsword")
    assert weapon is not None
    return weapon


@pytest.fixture(scope="module")
def attack_activity(longsword: Weapon) -> AttackActivity:
    activity = next(a for a in longsword.activities if a.kind == "attack")
    assert isinstance(activity, AttackActivity)
    return activity


def _gen1_classification(hit_type: HitType) -> tuple[bool, bool]:
    """Gen 1 ``HitType`` → Gen 2's ``(is_crit, is_hit)`` tuple."""
    return (
        hit_type == HitType.CRITICAL_HIT,
        hit_type in (HitType.HIT, HitType.CRITICAL_HIT),
    )


# ── primitive seam: kept die + classification, all three roll modes ──────────


@pytest.mark.parametrize(
    ("mode", "advantage", "disadvantage"),
    [("normal", False, False), ("advantage", True, False), ("disadvantage", False, True)],
)
@pytest.mark.parametrize("seed", SEEDS)
def test_attack_roll_primitives_keep_the_same_die_and_classify_alike(
    seed: int, mode: str, advantage: bool, disadvantage: bool, attack_activity: AttackActivity
) -> None:
    with _global_random_seeded(seed):
        gen1 = attack_roll(ATTACK_BONUS, TARGET_AC, advantage=advantage, disadvantage=disadvantage)
    gen1_natural = gen1.roll.total - gen1.roll.modifier

    gen2_natural = _roll_natural_d20(_ctx(seed), mode)  # type: ignore[arg-type]
    gen2 = _resolve_hit_outcome(
        gen2_natural, gen2_natural + ATTACK_BONUS, TARGET_AC, attack_activity
    )

    assert gen1_natural == gen2_natural, f"seed={seed} mode={mode}: kept die diverged"
    assert _gen1_classification(gen1.hit_type) == gen2, (
        f"seed={seed} mode={mode} natural={gen1_natural}: "
        f"gen1={gen1.hit_type} gen2=(crit,hit)={gen2}"
    )


def test_parity_corpus_exercises_every_outcome() -> None:
    """Guard against a vacuous corpus — 64 seeds × 3 modes must reach crit, hit, and miss."""
    seen: set[HitType] = set()
    for seed in SEEDS:
        for adv, dis in ((False, False), (True, False), (False, True)):
            with _global_random_seeded(seed):
                seen.add(
                    attack_roll(ATTACK_BONUS, TARGET_AC, advantage=adv, disadvantage=dis).hit_type
                )
    assert seen == {HitType.MISS, HitType.HIT, HitType.CRITICAL_HIT}


# ── end to end: the two public entry points, flat roll ───────────────────────


@pytest.mark.parametrize("seed", SEEDS)
def test_public_entry_points_agree_on_a_flat_longsword_swing(
    seed: int, longsword: Weapon, attack_activity: AttackActivity
) -> None:
    with _global_random_seeded(seed):
        gen1 = resolve_player_attack(
            action_type="attack",
            attack_bonus=ATTACK_BONUS,
            target_ac=TARGET_AC,
            damage_dice="1d8",
            damage_type="slashing",
            damage_modifier=3,
            target_name="mon:foe",
            target_hp_current=500,
            target_hp_max=500,
            active_effects=(),
            target_active_effects=(),
        )

    events: list[CombatEvent] = []
    resolve_activity(attack_activity, _ctx(seed, events), weapon=longsword)
    gen2 = next(e for e in events if isinstance(e, AttackRolled))

    assert gen1.attack_roll == gen2.roll_total, f"seed={seed}: attack totals diverged"
    assert (gen1.is_critical, gen1.hit) == (gen2.is_crit, gen2.is_hit), (
        f"seed={seed} total={gen1.attack_roll}: gen1=(crit,hit)=({gen1.is_critical}, {gen1.hit}) "
        f"gen2=({gen2.is_crit}, {gen2.is_hit})"
    )
