"""C12 — orchestrator-level condition gates (incapacitated, speed, charmed)."""

from __future__ import annotations

from typing import Any

import pytest

from dnd5e_engine import ActiveEffect, PlayerIntent
from dnd5e_engine.events import (
    ActorMoved,
    AttackFailed,
    AttackRolled,
    CastFailed,
    ConditionApplied,
    ConditionRemoved,
    Death,
    IntentSubmitted,
    MoveFailed,
    SaveRolled,
    TurnEnded,
)
from dnd5e_engine.orchestrator import (
    IntentRejectedError,
    _get_live,
    advance_monster_turn,
    start_combat,
    submit_player_intent,
)
from dnd5e_engine.specs import EncounterMemberSpec, PartyMemberSpec
from tests.e2e.harness import cell, events_of, grid_scene, run_async


def _hero(**kw: Any) -> PartyMemberSpec:
    base: dict[str, Any] = dict(
        entity_id="char:hero",
        name="Hero",
        initiative=20,
        hp_current=20,
        hp_max=20,
        attack_bonus=5,
        base_speed=30,
        zone_id=cell(0, 0),
    )
    base.update(kw)
    return PartyMemberSpec(**base)


def _foe(**kw: Any) -> EncounterMemberSpec:
    base: dict[str, Any] = dict(
        entity_id="mon:foe",
        entity_type="Monster",
        name="Foe",
        initiative=1,
        hp_current=50,
        hp_max=50,
        ac=1,
        zone_id=cell(1, 0),
    )
    base.update(kw)
    return EncounterMemberSpec(**base)


def _status(target_id: str, *statuses: str, origin: str = "test:cond") -> ActiveEffect:
    return ActiveEffect(
        id=f"effect:{'-'.join(statuses)}:{target_id}",
        name="Cond",
        origin=origin,
        target_id=target_id,
        statuses=set(statuses),
    )


def _start(
    session: str,
    party: list[PartyMemberSpec],
    encounter: list[EncounterMemberSpec],
    effects: Any = (),
) -> Any:
    return run_async(
        start_combat(
            session_id=session,
            party=party,
            encounter=encounter,
            scene_zones=None,
            grid_scene=grid_scene(),
            active_effects=list(effects),
            rng_seed=1,
        )
    )


@pytest.mark.parametrize(
    "status", ["incapacitated", "paralyzed", "stunned", "petrified", "unconscious"]
)
def test_incapacitating_condition_rejects_an_attack(status: str) -> None:
    start = _start(f"c12-incap-{status}", [_hero()], [_foe()], [_status("char:hero", status)])
    with pytest.raises(IntentRejectedError) as exc:
        run_async(
            submit_player_intent(
                start.handle,
                actor_id="char:hero",
                intent=PlayerIntent(
                    intent_type="attack", weapon_id="longsword", target_id="mon:foe"
                ),
            )
        )
    assert exc.value.reason == "actor_incapacitated"
    live = _get_live(start.handle)
    assert not events_of(live, IntentSubmitted)  # rejected BEFORE IntentSubmitted


def test_incapacitated_actor_may_still_pass_the_turn() -> None:
    start = _start("c12-incap-pass", [_hero()], [_foe()], [_status("char:hero", "incapacitated")])
    run_async(
        submit_player_intent(
            start.handle, actor_id="char:hero", intent=PlayerIntent(intent_type="pass")
        )
    )
    live = _get_live(start.handle)
    assert [e.actor_id for e in events_of(live, TurnEnded)] == ["char:hero"]


def test_stunned_actor_may_still_move_but_not_dash() -> None:
    # SRD 5.2 Stunned has no Speed clause; Dash is an action and is blocked.
    start = _start(
        "c12-stunned-move",
        [_hero()],
        [_foe(zone_id=cell(5, 5))],
        [_status("char:hero", "stunned")],
    )
    run_async(
        submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="move", target_zone_id=cell(1, 0)),
        )
    )
    assert _get_live(start.handle).actor_zone["char:hero"] == cell(1, 0)
    with pytest.raises(IntentRejectedError) as exc:
        run_async(
            submit_player_intent(
                start.handle, actor_id="char:hero", intent=PlayerIntent(intent_type="dash")
            )
        )
    assert exc.value.reason == "actor_incapacitated"


def test_incapacitated_monster_turn_records_a_pass() -> None:
    start = _start(
        "c12-incap-monster",
        [_hero(initiative=1)],
        [_foe(initiative=20, monster_template_slug="goblin-warrior")],
        [_status("mon:foe", "paralyzed")],
    )
    # NOTE: slug is "goblin-warrior" (the brief said "goblin", which is not a
    # canonical SRD slug and would make this assertion vacuous via
    # monster_unresolved).
    run_async(advance_monster_turn(start.handle))
    live = _get_live(start.handle)
    assert not events_of(live, AttackRolled)
    submitted = events_of(live, IntentSubmitted)
    assert submitted
    assert submitted[-1].actor_id == "mon:foe"
    assert submitted[-1].intent_type == "pass"


def _combatant(live: Any, entity_id: str) -> Any:
    return next(c for c in live.initiative if c.entity_id == entity_id)


@pytest.mark.parametrize(
    "status", ["grappled", "restrained", "paralyzed", "petrified", "unconscious"]
)
def test_speed_zero_condition_projects_zero_movement_and_fails_moves(status: str) -> None:
    start = _start(
        f"c12-speed0-{status}",
        [_hero()],
        [_foe(zone_id=cell(5, 5))],
        [_status("char:hero", status)],
    )
    live = _get_live(start.handle)
    assert _combatant(live, "char:hero").movement_remaining == 0
    run_async(
        submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="move", target_zone_id=cell(1, 0)),
        )
    )
    failed = events_of(live, MoveFailed)
    assert failed
    assert failed[-1].reason == "speed_zero"
    assert live.actor_zone["char:hero"] == cell(0, 0)


def test_dash_cannot_increase_a_zero_speed() -> None:
    # SRD 5.2 Grappled: "Your Speed is 0 and can't increase."
    start = _start(
        "c12-speed0-dash",
        [_hero()],
        [_foe(zone_id=cell(5, 5))],
        [_status("char:hero", "restrained")],
    )
    run_async(
        submit_player_intent(
            start.handle, actor_id="char:hero", intent=PlayerIntent(intent_type="dash")
        )
    )
    assert _combatant(_get_live(start.handle), "char:hero").movement_remaining == 0


def test_exhaustion_reduces_the_movement_budget_by_five_feet_per_level() -> None:
    start = _start(
        "c12-exh-speed",
        [_hero()],
        [_foe(zone_id=cell(5, 5))],
        [_status("char:hero", "exhaustion")],
    )
    assert _combatant(_get_live(start.handle), "char:hero").movement_remaining == 25


def test_unconditioned_actor_keeps_the_full_budget() -> None:
    start = _start("c12-speed-baseline", [_hero()], [_foe(zone_id=cell(5, 5))])
    assert _combatant(_get_live(start.handle), "char:hero").movement_remaining == 30


def test_speed_zero_monster_cannot_dash_toward_its_target() -> None:
    # SRD 5.2 Grappled: "Your Speed is 0 and can't increase." — the monster
    # approach gambit Dashes to close a gap it cannot otherwise cross; a
    # Speed-0 monster may not buy movement that way either.
    start = _start(
        "c12-speed0-monster-dash",
        [_hero(initiative=1, zone_id=cell(0, 0))],
        [_foe(initiative=20, zone_id=cell(3, 0), monster_template_slug="goblin-warrior")],
        [_status("mon:foe", "grappled")],
    )
    run_async(advance_monster_turn(start.handle))
    live = _get_live(start.handle)
    assert live.actor_zone["mon:foe"] == cell(3, 0)
    assert not [e for e in events_of(live, ActorMoved) if e.actor_id == "mon:foe"]
    assert _combatant(live, "mon:foe").movement_remaining == 0


def test_end_of_turn_repeat_save_honours_auto_fail_and_restrained_disadvantage() -> None:
    """SRD 5.2 Conditions on the ORCHESTRATOR repeat-save path: a Paralyzed
    creature auto-fails STR/DEX saves (no d20 drawn) while an unaffected
    ability still rolls; a Restrained creature rolls DEX at disadvantage."""
    start = _start(
        "c12-repeat-save",
        [_hero()],
        [_foe(zone_id=cell(5, 5))],
        [_status("char:hero", "paralyzed")],
    )
    live = _get_live(start.handle)
    live.repeat_save_on_turn_end[("char:hero", "effect:hold", "cast:hold-person:mon:foe")] = [
        {"ability": "wis", "dc": 13, "condition": "paralyzed", "caster_id": "mon:foe"}
    ]
    # ``pass`` is legal while Incapacitated and ends the turn.
    run_async(
        submit_player_intent(
            start.handle, actor_id="char:hero", intent=PlayerIntent(intent_type="pass")
        )
    )
    saves = [e for e in events_of(live, SaveRolled) if e.target_id == "char:hero"]
    assert saves
    assert saves[-1].ability == "wis"
    # WIS is not auto-failed; the roll happened normally.
    assert saves[-1].natural is not None

    start2 = _start(
        "c12-repeat-save-dex",
        [_hero()],
        [_foe(zone_id=cell(5, 5))],
        [_status("char:hero", "restrained")],
    )
    live2 = _get_live(start2.handle)
    live2.repeat_save_on_turn_end[("char:hero", "effect:web", "cast:web:mon:foe")] = [
        {"ability": "dex", "dc": 13, "condition": "restrained", "caster_id": "mon:foe"}
    ]
    run_async(
        submit_player_intent(
            start2.handle, actor_id="char:hero", intent=PlayerIntent(intent_type="pass")
        )
    )
    dex = [e for e in events_of(live2, SaveRolled) if e.target_id == "char:hero"][-1]
    assert dex.advantage == "disadvantage"
    assert "condition:target" in dex.sources

    start3 = _start(
        "c12-repeat-save-str",
        [_hero()],
        [_foe(zone_id=cell(5, 5))],
        [_status("char:hero", "paralyzed")],
    )
    live3 = _get_live(start3.handle)
    live3.repeat_save_on_turn_end[("char:hero", "effect:hold2", "cast:hold-person:mon:foe")] = [
        {"ability": "str", "dc": 13, "condition": "paralyzed", "caster_id": "mon:foe"}
    ]
    run_async(
        submit_player_intent(
            start3.handle, actor_id="char:hero", intent=PlayerIntent(intent_type="pass")
        )
    )
    strength = [e for e in events_of(live3, SaveRolled) if e.target_id == "char:hero"][-1]
    assert strength.succeeded is False
    assert strength.natural is None
    assert strength.roll_total == 0


# ---------------------------------------------------------------------------
# C12-S06 — Dropping to 0 Hit Points (SRD 5.2 "Damage and Healing")
# ---------------------------------------------------------------------------


def _victim(**kw: Any) -> PartyMemberSpec:
    base: dict[str, Any] = dict(
        entity_id="char:victim",
        name="Victim",
        initiative=1,
        hp_current=1,
        hp_max=20,
        ac=1,
        zone_id=cell(1, 0),
    )
    base.update(kw)
    return PartyMemberSpec(**base)


def _duel(session: str, victim: PartyMemberSpec) -> Any:
    return _start(
        session,
        [
            _hero(
                entity_id="char:attacker",
                name="Attacker",
                attack_bonus=99,
                zone_id=cell(0, 0),
            ),
            victim,
        ],
        [_foe(initiative=5, hp_current=20, hp_max=20, ac=99, zone_id=cell(5, 5))],
    )


def _stab(start: Any) -> Any:
    run_async(
        submit_player_intent(
            start.handle,
            actor_id="char:attacker",
            intent=PlayerIntent(
                intent_type="attack", weapon_id="longsword", target_id="char:victim"
            ),
        )
    )
    return _get_live(start.handle)


def test_character_at_zero_hp_gains_unconscious_and_is_incapacitated_and_prone() -> None:
    live = _stab(_duel("c12-zero-hp", _victim()))
    applied = [e for e in events_of(live, ConditionApplied) if e.target_id == "char:victim"]
    assert [e.condition for e in applied] == ["unconscious"]
    victim = _combatant(live, "char:victim")
    names = [c.condition for c in victim.conditions]
    assert "unconscious" in names
    assert victim.hp_current == 0
    assert victim.is_alive is True
    assert victim.movement_remaining == 0
    assert not events_of(live, Death)


def test_massive_damage_kills_outright() -> None:
    # hp_max 1: any longsword hit leaves remainder >= max after reaching 0.
    live = _stab(_duel("c12-massive", _victim(hp_current=1, hp_max=1)))
    deaths = [e for e in events_of(live, Death) if e.target_id == "char:victim"]
    assert deaths
    assert deaths[0].reason == "instant_kill"
    assert not [e for e in events_of(live, ConditionApplied) if e.target_id == "char:victim"]


def test_damage_while_at_zero_hp_is_a_death_save_failure() -> None:
    # C15 repair: attacker moved beyond 5 ft — the adjacent stab auto-crits vs
    # an Unconscious target (C12), and a crit at 0 HP now correctly counts two
    # failures (SRD §Damage at 0 HP). A melee weapon cannot reach from 15 ft,
    # so the attacker switches to a ranged weapon (Shortbow, 80 ft normal
    # range) to keep this an ORDINARY (non-crit) hit, preserving the test's
    # original intent: ordinary damage at 0 HP is exactly one failure.
    start = _start(
        "c12-damage-at-zero",
        [
            _hero(
                entity_id="char:attacker",
                name="Attacker",
                attack_bonus=99,
                zone_id=cell(0, 0),
            ),
            _victim(hp_current=1, hp_max=40, zone_id=cell(3, 0)),
        ],
        [_foe(initiative=5, hp_current=20, hp_max=20, ac=99, zone_id=cell(5, 5))],
    )

    def _shoot() -> Any:
        run_async(
            submit_player_intent(
                start.handle,
                actor_id="char:attacker",
                intent=PlayerIntent(
                    intent_type="attack", weapon_id="shortbow", target_id="char:victim"
                ),
            )
        )
        return _get_live(start.handle)

    live = _shoot()
    # Attacker's turn ended; skip the foe and the victim (victim rolls a death
    # save at turn start), then shoot again on the attacker's next turn.
    run_async(advance_monster_turn(start.handle))
    run_async(
        submit_player_intent(
            start.handle, actor_id="char:victim", intent=PlayerIntent(intent_type="pass")
        )
    )
    failures_before = _combatant(live, "char:victim").death_saves.get("failures", 0)
    _shoot()
    assert _combatant(live, "char:victim").death_saves.get("failures", 0) == failures_before + 1


def test_healing_from_zero_removes_unconscious_and_leaves_prone() -> None:
    from dnd5e_engine.events import HealingApplied
    from dnd5e_engine.orchestrator import _emit

    live = _stab(_duel("c12-revive", _victim()))
    _emit(live, HealingApplied(target_id="char:victim", amount=5))
    names = [c.condition for c in _combatant(live, "char:victim").conditions]
    assert "unconscious" not in names
    assert "prone" in names
    removed = [e for e in events_of(live, ConditionRemoved) if e.target_id == "char:victim"]
    assert removed
    assert removed[-1].condition == "unconscious"


def test_monster_at_zero_hp_dies_outright_with_no_death_save_path() -> None:
    # SRD 5.2 "Monster Death" — monsters die the instant they drop to 0 HP;
    # only Characters fall Unconscious and roll death saves.
    start = _start(
        "c12-monster-death",
        [_hero(attack_bonus=99)],
        [_foe(hp_current=1, hp_max=30, ac=1, zone_id=cell(1, 0))],
    )
    run_async(
        submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="attack", weapon_id="longsword", target_id="mon:foe"),
        )
    )
    live = _get_live(start.handle)
    deaths = [e for e in events_of(live, Death) if e.target_id == "mon:foe"]
    assert [e.reason for e in deaths] == ["damage"]
    assert not [e for e in events_of(live, ConditionApplied) if e.target_id == "mon:foe"]
    foe = _combatant(live, "mon:foe")
    assert foe.death_saves in ({}, None)


class _FixedRng:
    """Minimal ``random.Random`` stand-in returning a fixed d20 roll."""

    def __init__(self, value: int) -> None:
        self._value = value

    def randint(self, a: int, b: int) -> int:
        return self._value


def test_condition_removed_keeps_a_condition_another_live_effect_still_imposes() -> None:
    # Two effects impose "restrained"; one is dropped (EffectExpired +
    # ConditionRemoved, the ``_drop_concentration`` order). The condition must
    # survive on the still-imposing effect — same multi-source stacking guard
    # ``_emit_apply_effect_expired`` already honours.
    from dnd5e_engine.events import EffectExpired
    from dnd5e_engine.orchestrator import _emit

    web = _status("char:hero", "restrained", origin="cast:web:mon:foe")
    web = web.model_copy(update={"id": "effect:web:char:hero"})
    vine = _status("char:hero", "restrained", origin="cast:vine:mon:foe")
    vine = vine.model_copy(update={"id": "effect:vine:char:hero"})
    start = _start("c12-two-sources", [_hero()], [_foe(zone_id=cell(5, 5))], [web, vine])
    live = _get_live(start.handle)
    assert [c.condition for c in _combatant(live, "char:hero").conditions] == [
        "restrained",
        "restrained",
    ]

    _emit(
        live,
        EffectExpired(
            target_id="char:hero",
            effect_id=web.id,
            origin=web.origin,
            reason="concentration_drop",
        ),
    )
    _emit(live, ConditionRemoved(target_id="char:hero", condition="restrained"))

    names = [c.condition for c in _combatant(live, "char:hero").conditions]
    assert names == ["restrained"]
    assert "restrained" in live.active_conditions.get("char:hero", set())


def test_nat_twenty_death_save_revive_is_event_symmetric_and_leaves_prone() -> None:
    from dnd5e_engine.orchestrator import _maybe_roll_death_save

    start = _duel("c12-nat20-revive", _victim())
    live = _stab(start)
    assert "unconscious" in live.active_conditions.get("char:victim", set())

    live.current_turn_index = next(
        i for i, c in enumerate(live.initiative) if c.entity_id == "char:victim"
    )
    live.rng = _FixedRng(20)  # type: ignore[assignment]
    _maybe_roll_death_save(live)

    assert "unconscious" not in live.active_conditions.get("char:victim", set())
    names = [c.condition for c in _combatant(live, "char:victim").conditions]
    assert "unconscious" not in names
    assert "prone" in names
    removed = [e for e in events_of(live, ConditionRemoved) if e.target_id == "char:victim"]
    assert [e.condition for e in removed] == ["unconscious"]
    applied = [
        e.condition for e in events_of(live, ConditionApplied) if e.target_id == "char:victim"
    ]
    assert applied == ["unconscious", "prone"]


def test_zero_damage_at_zero_hp_is_not_a_death_save_failure() -> None:
    # ``activities/apply.py`` emits ``DamageApplied`` unconditionally, so an
    # immune damage type (or one fully absorbed by temp HP) arrives with
    # ``amount=0``. SRD 5.2 charges a failure for *damage taken* only.
    from dnd5e_engine.events import DamageApplied
    from dnd5e_engine.orchestrator import _emit

    live = _stab(_duel("c12-zero-damage", _victim()))
    before = _combatant(live, "char:victim").death_saves.get("failures", 0)
    _emit(
        live,
        DamageApplied(target_id="char:victim", amount=0, damage_type="fire", is_overkill=False),
    )
    assert _combatant(live, "char:victim").death_saves.get("failures", 0) == before


def _charm(target_id: str, charmer_id: str) -> ActiveEffect:
    return ActiveEffect(
        id="effect:charm",
        name="Charmed",
        origin=f"cast:charm-person:{charmer_id}",
        target_id=target_id,
        statuses={"charmed"},
    )


def test_charmed_actor_cannot_attack_the_charmer() -> None:
    start = _start("c12-charm-attack", [_hero()], [_foe()], [_charm("char:hero", "mon:foe")])
    run_async(
        submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="attack", weapon_id="longsword", target_id="mon:foe"),
        )
    )
    live = _get_live(start.handle)
    failed = events_of(live, AttackFailed)
    assert failed
    assert failed[-1].reason == "target_is_charmer"
    assert failed[-1].target_id == "mon:foe"
    assert not events_of(live, AttackRolled)
    assert _combatant(live, "char:hero").action_available is True  # nothing spent, turn kept


def test_charmed_actor_may_attack_someone_else() -> None:
    other = _foe(entity_id="mon:other", name="Other", zone_id=cell(0, 1))
    start = _start("c12-charm-other", [_hero()], [_foe(), other], [_charm("char:hero", "mon:foe")])
    run_async(
        submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="attack", weapon_id="longsword", target_id="mon:other"),
        )
    )
    assert events_of(_get_live(start.handle), AttackRolled)


def test_charmed_actor_cannot_target_the_charmer_with_a_harmful_spell() -> None:
    start = _start(
        "c12-charm-cast",
        [_hero(spells_known=["fire-bolt"])],
        [_foe()],
        [_charm("char:hero", "mon:foe")],
    )
    run_async(
        submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(
                intent_type="cast_spell", spell_id="fire-bolt", target_id="mon:foe"
            ),
        )
    )
    failed = events_of(_get_live(start.handle), CastFailed)
    assert failed
    assert failed[-1].reason == "target_is_charmer"


def test_charmed_actor_may_target_the_charmer_with_a_beneficial_spell() -> None:
    # SRD 5.2 Charmed only bars "damaging abilities or magical effects" - a
    # utility-only cantrip (no attack/damage/save activity) aimed at the
    # charmer is exactly the carve-out the ruling preserves.
    start = _start(
        "c12-charm-beneficial",
        [_hero(spells_known=["guidance"])],
        [_foe()],
        [_charm("char:hero", "mon:foe")],
    )
    run_async(
        submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="cast_spell", spell_id="guidance", target_id="mon:foe"),
        )
    )
    live = _get_live(start.handle)
    assert not events_of(live, CastFailed)
    submitted = [e for e in events_of(live, IntentSubmitted) if e.intent_type == "cast_spell"]
    assert submitted
    assert submitted[-1].target_id == "mon:foe"


def test_unknown_charmer_imposes_no_restriction() -> None:
    start = _start("c12-charm-unknown", [_hero()], [_foe()], [_status("char:hero", "charmed")])
    run_async(
        submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="attack", weapon_id="longsword", target_id="mon:foe"),
        )
    )
    assert events_of(_get_live(start.handle), AttackRolled)


# ---------------------------------------------------------------------------
# Condition immunity — the immune target never acquires the condition
# ---------------------------------------------------------------------------


def test_condition_immunity_keeps_an_effect_status_off_the_combatant() -> None:
    """SRD §Condition Immunity — ``activities/effects.py`` already suppresses
    the ``ConditionApplied`` for an immune target; the ``EffectApplied`` fold
    must not smuggle the status onto ``Combatant.conditions`` behind it, or
    every C12 gate (action block, Speed, save auto-fail, auto-crit) fires
    against a creature that cannot have the condition at all."""
    start = _start(
        "c12-immune-fold",
        [_hero(initiative=1)],
        [
            _foe(
                initiative=20,
                monster_template_slug="goblin-warrior",
                condition_immunities=["paralyzed"],
                base_speed=30,
            )
        ],
        [_status("mon:foe", "paralyzed")],
    )
    live = _get_live(start.handle)
    foe = _combatant(live, "mon:foe")
    assert [ac.condition for ac in foe.conditions] == []
    # Speed is untouched: the Paralyzed Speed-0 row never applies.
    assert foe.movement_remaining == 30
    # ...and it is free to take its turn.
    run_async(advance_monster_turn(start.handle))
    live = _get_live(start.handle)
    assert events_of(live, AttackRolled)
    submitted = [e for e in events_of(live, IntentSubmitted) if e.actor_id == "mon:foe"]
    assert submitted[-1].intent_type != "pass"


def test_condition_immunity_gates_the_runtime_effect_applied_fold() -> None:
    """The mid-combat ``EffectApplied`` fold (not just the start_combat seed)
    honours the immunity, so ``Combatant.conditions`` and the host-facing
    ``live.active_conditions`` stay in agreement."""
    from dnd5e_engine.events import EffectApplied
    from dnd5e_engine.orchestrator import _emit

    start = _start(
        "c12-immune-runtime",
        [_hero(condition_immunities=["paralyzed"])],
        [_foe()],
    )
    live = _get_live(start.handle)
    _emit(live, EffectApplied(effect=_status("char:hero", "paralyzed")))
    assert [ac.condition for ac in _combatant(live, "char:hero").conditions] == []
    assert live.active_conditions.get("char:hero", set()) == set()
    assert _combatant(live, "char:hero").movement_remaining == 30


def test_condition_immunity_does_not_auto_fail_saves() -> None:
    """A creature immune to Paralyzed keeps rolling its STR/DEX saves — the
    ``passive_save_auto_fail`` projection reads ``Combatant.conditions``."""
    start = _start(
        "c12-immune-save",
        [_hero(condition_immunities=["paralyzed"])],
        [_foe(zone_id=cell(5, 5))],
        [_status("char:hero", "paralyzed")],
    )
    live = _get_live(start.handle)
    live.repeat_save_on_turn_end[("char:hero", "effect:hold", "cast:hold-person:mon:foe")] = [
        {"ability": "str", "dc": 13, "condition": "paralyzed", "caster_id": "mon:foe"}
    ]
    run_async(
        submit_player_intent(
            start.handle, actor_id="char:hero", intent=PlayerIntent(intent_type="pass")
        )
    )
    strength = [e for e in events_of(live, SaveRolled) if e.target_id == "char:hero"][-1]
    assert strength.natural is not None  # a real d20 was drawn, not an auto-fail


# ---------------------------------------------------------------------------
# Charmed — the monster turn path (symmetry with the player path)
# ---------------------------------------------------------------------------


def test_charmed_monster_will_not_attack_its_charmer() -> None:
    start = _start(
        "c12-charm-monster",
        [_hero(initiative=1)],
        [_foe(initiative=20, monster_template_slug="goblin-warrior")],
        [_charm("mon:foe", "char:hero")],
    )
    run_async(advance_monster_turn(start.handle))
    live = _get_live(start.handle)
    assert not events_of(live, AttackRolled)
    submitted = [e for e in events_of(live, IntentSubmitted) if e.actor_id == "mon:foe"]
    assert submitted
    assert submitted[-1].intent_type == "pass"


def test_charmed_monster_still_attacks_someone_who_is_not_its_charmer() -> None:
    other = _hero(entity_id="char:other", name="Other", initiative=1, zone_id=cell(1, 1))
    start = _start(
        "c12-charm-monster-other",
        [_hero(initiative=1), other],
        [_foe(initiative=20, monster_template_slug="goblin-warrior")],
        [_charm("mon:foe", "char:hero")],
    )
    run_async(advance_monster_turn(start.handle))
    live = _get_live(start.handle)
    assert events_of(live, AttackRolled)
    assert events_of(live, AttackRolled)[-1].target_id == "char:other"


# ---------------------------------------------------------------------------
# A Character hydrated into combat already at 0 HP
# ---------------------------------------------------------------------------


def test_character_hydrated_at_zero_hp_starts_unconscious() -> None:
    """SRD 5.2 "Dropping to 0 Hit Points" — a host resuming a saved combat with
    a downed PC must get a PC that is Unconscious (and therefore Incapacitated
    and Prone), not one that can act."""
    start = _start(
        "c12-hydrate-zero-hp",
        [_hero(hp_current=0)],
        [_foe()],
    )
    live = _get_live(start.handle)
    hero = _combatant(live, "char:hero")
    # BOTH condition stores must agree: the typed list every projection reads,
    # and the coarse name set ``views.py`` shows the host (and the bridge
    # rebuilds host storage from). A hydration that set only the former would
    # leave a host mirroring via ``active_conditions`` with a downed PC that
    # looks fine.
    assert "unconscious" in [ac.condition for ac in hero.conditions]
    assert "unconscious" in live.active_conditions.get("char:hero", set())
    assert hero.movement_remaining == 0
    with pytest.raises(IntentRejectedError) as exc:
        run_async(
            submit_player_intent(
                start.handle,
                actor_id="char:hero",
                intent=PlayerIntent(
                    intent_type="attack", weapon_id="longsword", target_id="mon:foe"
                ),
            )
        )
    assert exc.value.reason == "actor_incapacitated"
