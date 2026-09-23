"""C15 Task 4 — Versatile grip, ``DamageApplied`` source/crit attribution,
the crit-at-0-HP death-save clause, and the weapon-tagged to-hit sidecar lift.

Mirrors ``tests/test_weapon_damage_bonus_sidecar.py``'s direct-resolver
pattern for the resolver-level pieces (versatile, source_id/is_crit,
weapon-tagged to-hit) and ``tests/activities/test_build_context.py`` for the
sidecar-lift piece. The orchestrator-level grip classification
(``_versatile_grip_applies``) and the full e2e wiring are covered by
``tests/e2e/test_c15_attack_rules.py::test_c15_s04_...``.
"""

from __future__ import annotations

import random

from dnd5e_srd_data.loader import BundledAssetLoader

from dnd5e_engine.activities.build_context import build_activity_context
from dnd5e_engine.activities.context import ActivityResolutionContext
from dnd5e_engine.activities.resolver import resolve_activity
from dnd5e_engine.death_saves import DeathSaveState
from dnd5e_engine.events import AttackRolled, DamageApplied
from dnd5e_engine.orchestrator import _versatile_grip_applies
from dnd5e_engine.types.combat import Combatant

_LOADER = BundledAssetLoader()


class _MaxRandom(random.Random):
    """Deterministic stand-in RNG: every ``randint(a, b)`` draw returns ``b``
    (the die's max face), so which die size was rolled is unambiguous from
    the returned amount — a 1d8 draw returns 8, a 1d10 draw returns 10.
    """

    def randint(self, a: int, b: int) -> int:
        del a
        return b


def _attacker(**overrides) -> Combatant:
    base = dict(
        entity_id="char:hero",
        entity_type="Character",
        name="Hero",
        initiative=10,
        hp_current=20,
        hp_max=20,
        strength=16,
    )
    base.update(overrides)
    return Combatant(**base)


def _target(**overrides) -> Combatant:
    base = dict(
        entity_id="mon:foe",
        entity_type="Monster",
        name="Foe",
        initiative=1,
        hp_current=500,
        hp_max=500,
        ac=1,
    )
    base.update(overrides)
    return Combatant(**base)


def _resolve_longsword(
    *, use_versatile_damage: bool, rng: random.Random, force_d20: int = 15, **ctx_kwargs
) -> list:
    longsword = _LOADER.get_weapon("longsword")
    assert longsword is not None
    activity = next(a for a in longsword.activities if a.kind == "attack")
    events: list = []
    ctx = ActivityResolutionContext(
        rng=rng,
        caster=_attacker(),
        targets=[_target()],
        event_emitter=events.append,
        caster_abilities={"str": 16, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10},
        caster_proficiency_bonus=2,
        caster_level=1,
        variables={"force_d20": force_d20},
        use_versatile_damage=use_versatile_damage,
        **ctx_kwargs,
    )
    resolve_activity(activity, ctx, weapon=longsword)
    return events


def _hit_damage(events: list) -> DamageApplied:
    hits = [e for e in events if isinstance(e, DamageApplied)]
    assert len(hits) == 1
    return hits[0]


# ── (a) Versatile grip ────────────────────────────────────────────────────


def test_versatile_two_handed_rolls_1d10_band():
    """A natural (unpinned) roll with the versatile flag set lands the
    Longsword's damage in the 1d10+3 band (4..13), never above it."""
    for seed in range(20):
        events = _resolve_longsword(use_versatile_damage=True, rng=random.Random(seed))
        amount = _hit_damage(events).amount
        assert 1 + 3 <= amount <= 10 + 3


def test_versatile_two_handed_rolls_exactly_the_1d10_die_pinned():
    """With a pinned (max-face) die, the versatile grip rolls exactly
    10 (1d10 max) + 3 (STR mod) = 13 — proof it is the 1d10 versatile die,
    not the 1d8 default, that got rolled."""
    events = _resolve_longsword(use_versatile_damage=True, rng=_MaxRandom())
    assert _hit_damage(events).amount == 10 + 3


def test_default_grip_rolls_exactly_the_1d8_die_pinned():
    """Without the versatile flag the SAME pinned rng rolls the ordinary
    1d8 die: 8 (1d8 max) + 3 (STR mod) = 11."""
    events = _resolve_longsword(use_versatile_damage=False, rng=_MaxRandom())
    assert _hit_damage(events).amount == 8 + 3


def test_versatile_flag_ignored_on_a_non_versatile_weapon():
    """A weapon with no ``versatile_damage`` (Shortsword) ignores the flag
    and rolls its ordinary die unchanged."""
    shortsword = _LOADER.get_weapon("shortsword")
    assert shortsword is not None
    assert shortsword.versatile_damage is None
    activity = next(a for a in shortsword.activities if a.kind == "attack")
    events: list = []
    ctx = ActivityResolutionContext(
        rng=_MaxRandom(),
        caster=_attacker(),
        targets=[_target()],
        event_emitter=events.append,
        caster_abilities={"str": 16, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10},
        caster_proficiency_bonus=2,
        caster_level=1,
        variables={"force_d20": 15},
        use_versatile_damage=True,
    )
    resolve_activity(activity, ctx, weapon=shortsword)
    part = shortsword.damage_parts[0]
    max_face = int(part.dice.split("d")[1])
    assert _hit_damage(events).amount == max_face + 3


def test_versatile_grip_ignored_when_weapon_is_thrown_beyond_reach():
    """SRD Versatile — "to make a MELEE attack." A Spear (Thrown +
    Versatile) thrown beyond its 5ft melee reach is a ranged attack; the
    orchestrator-level classifier must not apply the versatile grip there.
    """
    spear = _LOADER.get_weapon("spear")
    assert spear is not None
    assert _versatile_grip_applies(spear, None) is True
    assert _versatile_grip_applies(spear, 5) is True
    assert _versatile_grip_applies(spear, 6) is False
    assert _versatile_grip_applies(spear, 20) is False


def test_versatile_grip_never_applies_without_the_property():
    dagger = _LOADER.get_weapon("dagger")
    assert dagger is not None
    assert _versatile_grip_applies(dagger, None) is False


def test_versatile_grip_absent_weapon_is_false():
    assert _versatile_grip_applies(None, None) is False


# ── (b) source_id attribution ──────────────────────────────────────────────


def test_base_weapon_damage_attributes_to_weapon_slug():
    events = _resolve_longsword(use_versatile_damage=False, rng=random.Random(7))
    assert _hit_damage(events).source_id == "longsword"


def test_graze_mastery_proc_attributes_to_mastery_graze():
    """SRD §Graze — fires on a MISS; force a miss (natural 1) and confirm
    the flat mastery damage event is separately attributed."""
    graze_weapon = _LOADER.get_weapon("greatsword")
    assert graze_weapon is not None
    assert graze_weapon.mastery == "graze"
    activity = next(a for a in graze_weapon.activities if a.kind == "attack")
    events: list = []
    ctx = ActivityResolutionContext(
        rng=random.Random(3),
        caster=_attacker(),
        targets=[_target()],
        event_emitter=events.append,
        caster_abilities={"str": 16, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10},
        caster_proficiency_bonus=2,
        caster_level=1,
        variables={"force_d20": 1},  # SRD nat-1 is always a miss
    )
    resolve_activity(activity, ctx, weapon=graze_weapon)
    graze_events = [e for e in events if isinstance(e, DamageApplied)]
    assert len(graze_events) == 1
    assert graze_events[0].source_id == "mastery:graze"
    assert graze_events[0].is_crit is False


# ── (c) is_crit attribution ─────────────────────────────────────────────────


def test_natural_20_marks_damage_event_as_crit():
    events = _resolve_longsword(use_versatile_damage=False, rng=random.Random(9), force_d20=20)
    assert _hit_damage(events).is_crit is True


def test_normal_hit_does_not_mark_damage_event_as_crit():
    events = _resolve_longsword(use_versatile_damage=False, rng=random.Random(9), force_d20=15)
    assert _hit_damage(events).is_crit is False


# ── (d) crit-at-0HP two-failure clause ──────────────────────────────────────


def test_ordinary_damage_at_0_hp_records_one_failure():
    state = DeathSaveState()
    outcome = state.apply_damage_while_unconscious(False)
    assert state.failures == 1
    assert outcome == "ongoing"


def test_critical_damage_at_0_hp_records_two_failures():
    """SRD 5.2 §Damage at 0 Hit Points — a Critical Hit counts as TWO
    Death Saving Throw failures instead of one. Delta vs the ordinary-hit
    case above: +2, not +1."""
    state = DeathSaveState()
    outcome = state.apply_damage_while_unconscious(True)
    assert state.failures == 2
    assert outcome == "ongoing"


def test_critical_damage_at_0_hp_with_one_existing_failure_kills():
    """1 existing failure + a crit's 2 more = 3 -> "dead"."""
    state = DeathSaveState(failures=1)
    outcome = state.apply_damage_while_unconscious(True)
    assert state.failures == 3
    assert outcome == "dead"


# ── (e) weapon-tagged to-hit sidecar lift ───────────────────────────────────


def test_passive_weapon_to_hit_bonus_lifted_into_typed_context_field():
    """Mirrors ``test_passive_weapon_damage_bonus_reshaped_into_typed_field``
    (tests/activities/test_build_context.py): the orchestrator's
    action-type-tagged ``passive_weapon_to_hit_bonus`` sidecar key (written
    by ``_fold_active_effect_changes``'s ``weapon_only`` branch) must be
    lifted into its own typed ``ActivityResolutionContext`` field, mirroring
    how ``passive_weapon_damage_bonus`` was already closed.
    """
    c = _attacker()
    payload = {c.entity_id: {"passive_weapon_to_hit_bonus": "+3"}}
    ctx = build_activity_context(
        c,
        [c],
        rng=random.Random(1),
        event_emitter=lambda e: None,
        slot_level=1,
        base_spell_level=1,
        spellcasting_ability="int",
        concentration=False,
        source_passive_effects=[],
        spell_book={},
        passive_damage_modifiers=payload,
        save_modifiers={},
    )
    assert ctx.passive_weapon_attack_bonus[c.entity_id] == "+3"


def test_weapon_tagged_to_hit_bonus_raises_attack_rolled_total():
    """The lifted sidecar must actually reach the attack roll: a weapon
    swing with the sidecar populated rolls a higher ``AttackRolled.roll_total``
    than the same swing without it, by exactly the bonus (a flat literal
    bonus consumes no dice, so the seeded stream + natural roll are
    otherwise identical).
    """

    def _roll_total(passive_weapon_attack_bonus: dict) -> int:
        longsword = _LOADER.get_weapon("longsword")
        assert longsword is not None
        activity = next(a for a in longsword.activities if a.kind == "attack")
        events: list = []
        ctx = ActivityResolutionContext(
            rng=random.Random(11),
            caster=_attacker(),
            targets=[_target()],
            event_emitter=events.append,
            caster_abilities={"str": 16, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10},
            caster_proficiency_bonus=2,
            caster_level=1,
            variables={"force_d20": 15},
            passive_weapon_attack_bonus=passive_weapon_attack_bonus,  # type: ignore[call-arg]
        )
        resolve_activity(activity, ctx, weapon=longsword)
        rolls = [e for e in events if isinstance(e, AttackRolled)]
        assert len(rolls) == 1
        return rolls[0].roll_total

    base_total = _roll_total({})
    buffed_total = _roll_total({"char:hero": "+3"})
    assert buffed_total == base_total + 3


def test_weapon_tagged_to_hit_bonus_absent_attacker_contributes_zero():
    def _roll_total(passive_weapon_attack_bonus: dict) -> int:
        longsword = _LOADER.get_weapon("longsword")
        assert longsword is not None
        activity = next(a for a in longsword.activities if a.kind == "attack")
        events: list = []
        ctx = ActivityResolutionContext(
            rng=random.Random(11),
            caster=_attacker(),
            targets=[_target()],
            event_emitter=events.append,
            caster_abilities={"str": 16, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10},
            caster_proficiency_bonus=2,
            caster_level=1,
            variables={"force_d20": 15},
            passive_weapon_attack_bonus=passive_weapon_attack_bonus,  # type: ignore[call-arg]
        )
        resolve_activity(activity, ctx, weapon=longsword)
        rolls = [e for e in events if isinstance(e, AttackRolled)]
        return rolls[0].roll_total

    assert _roll_total({}) == _roll_total({"mon:someone_else": "+5"})
