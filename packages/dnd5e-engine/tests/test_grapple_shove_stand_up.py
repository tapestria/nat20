"""C14 Task 6 — the Unarmed Strike Grapple option and its escape.

SRD 5.2 (Unarmed Strike, "Grapple"): "The target must succeed on a Strength
or Dexterity saving throw (it chooses which), or it has the Grappled
condition. The DC for the saving throw and any escape attempts equals 8 plus
your Strength modifier and Proficiency Bonus."

SRD 5.2 ("Ending a Grapple"): "A Grappled creature can use its action to
make a Strength (Athletics) or Dexterity (Acrobatics) check against the
grapple's escape DC, ending the condition on itself on a success. The
condition also ends if the grappler has the Incapacitated condition..."

Controller ruling R3 (deterministic choice policy): the target saves with
whichever of STR/DEX has the higher save modifier (tie -> STR); the escaper
picks Athletics vs Acrobatics by higher check modifier (tie -> Athletics/STR).

Out of scope (BACKLOG): the size gate, the free-hand gate, and the
distance-exceeded auto-release (no forced-move currently separates a
grappled pair).

Task 7 appends its own test classes (Shove / Stand Up) to this module.
"""

from __future__ import annotations

import pytest

from dnd5e_engine import PlayerIntent
from dnd5e_engine.events import (
    CheckRolled,
    CombatantMoved,
    ConditionApplied,
    ConditionRemoved,
    SaveRolled,
)
from dnd5e_engine.orchestrator import (
    IntentRejectedError,
    _condition_source_entity,
    _effective_speed,
    _emit,
    _find_combatant,
    _get_live,
    submit_player_intent,
)
from dnd5e_engine.specs import EncounterMemberSpec, PartyMemberSpec
from dnd5e_engine.types.conditions import ActiveCondition
from tests.e2e.harness import cell, events_of, grid_scene, run_async


def _grapple_party(**overrides: object) -> list[PartyMemberSpec]:
    base = dict(
        entity_id="char:brute",
        name="Brute",
        initiative=20,
        hp_current=30,
        hp_max=30,
        strength=18,
        character_level=5,
        zone_id=cell(0, 0),
    )
    base.update(overrides)
    return [PartyMemberSpec(**base)]  # type: ignore[arg-type]


def _target_party(**overrides: object) -> PartyMemberSpec:
    base = dict(
        entity_id="char:target",
        name="Target",
        initiative=10,
        hp_current=20,
        hp_max=20,
        strength=12,
        dexterity=12,
        zone_id=cell(1, 0),
    )
    base.update(overrides)
    return PartyMemberSpec(**base)  # type: ignore[arg-type]


def _foe_encounter(**overrides: object) -> list[EncounterMemberSpec]:
    base = dict(
        entity_id="mon:foe",
        entity_type="Monster",
        name="Foe",
        initiative=1,
        hp_current=10,
        hp_max=10,
        ac=10,
        zone_id=cell(9, 9),
    )
    base.update(overrides)
    return [EncounterMemberSpec(**base)]  # type: ignore[arg-type]


async def _start_grapple_combat(
    session_id: str,
    *,
    target_zone: str = cell(1, 0),
    rng_seed: int = 7,
    **brute_overrides: object,
):
    party = _grapple_party(**brute_overrides)
    party.append(_target_party(zone_id=target_zone))
    return await start_combat_with(session_id, party, rng_seed=rng_seed)


async def start_combat_with(session_id: str, party: list[PartyMemberSpec], *, rng_seed: int):
    from dnd5e_engine.orchestrator import start_combat

    return await start_combat(
        session_id=session_id,
        party=party,
        encounter=_foe_encounter(),
        scene_zones=None,
        grid_scene=grid_scene(),
        rng_seed=rng_seed,
    )


class TestGrappleSave:
    def test_grapple_within_reach_rolls_save_and_ends_turn_on_failure(self):
        """(a) A level-5 STR-18 brute's grapple vs an adjacent target rolls a
        DC 15 save; on failure it applies Grappled with the stored escape DC,
        the grappler resolves via ``_condition_source_entity``, the target's
        speed drops to 0, and the brute's turn ends."""

        async def _run():
            # STR 1 / DEX 1 guarantees the save fails regardless of the d20.
            start = await _start_grapple_combat("t6-a-grapple-save-fail")
            live = _get_live(start.handle)
            for idx, c in enumerate(live.initiative):
                if c.entity_id == "char:target":
                    live.initiative[idx] = c.model_copy(update={"strength": 1, "dexterity": 1})
                    break
            await submit_player_intent(
                start.handle,
                actor_id="char:brute",
                intent=PlayerIntent(intent_type="grapple", target_id="char:target"),
            )
            return _get_live(start.handle)

        live = run_async(_run())
        rolled = next(e for e in events_of(live, SaveRolled) if e.target_id == "char:target")
        assert rolled.ability in ("str", "dex")
        assert rolled.dc == 15
        applied = [e for e in events_of(live, ConditionApplied) if e.target_id == "char:target"]
        assert any(e.condition == "grappled" for e in applied)
        target = _find_combatant(live, "char:target")
        assert target is not None
        cond = next(ac for ac in target.conditions if ac.condition == "grappled")
        assert cond.save_dc == 15
        assert _condition_source_entity(live, target, "grappled") == "char:brute"
        from dnd5e_engine.orchestrator import _effective_speed

        assert _effective_speed(target) == 0
        assert live.current_actor_id != "char:brute"


class TestGrappleRange:
    def test_grapple_beyond_5ft_is_rejected_with_no_roll(self):
        """(b) A target beyond 5 ft is rejected out-of-range with no d20
        drawn and no state change."""

        async def _run():
            start = await _start_grapple_combat("t6-b-grapple-out-of-range", target_zone=cell(9, 0))
            with pytest.raises(IntentRejectedError) as exc_info:
                await submit_player_intent(
                    start.handle,
                    actor_id="char:brute",
                    intent=PlayerIntent(intent_type="grapple", target_id="char:target"),
                )
            return exc_info, _get_live(start.handle)

        exc_info, live = run_async(_run())
        assert exc_info.value.reason == "out_of_range"
        assert not events_of(live, SaveRolled)
        brute = next(c for c in live.initiative if c.entity_id == "char:brute")
        assert brute.action_available is True


class TestGrappleSaveSuccess:
    def test_grapple_save_success_applies_no_condition(self):
        """(c) A successful save applies no Grappled condition."""

        async def _run():
            start = await _start_grapple_combat("t6-c-grapple-save-success")
            live = _get_live(start.handle)
            # Huge STR/DEX guarantees the save succeeds regardless of the d20.
            for idx, c in enumerate(live.initiative):
                if c.entity_id == "char:target":
                    live.initiative[idx] = c.model_copy(update={"strength": 30, "dexterity": 30})
                    break
            await submit_player_intent(
                start.handle,
                actor_id="char:brute",
                intent=PlayerIntent(intent_type="grapple", target_id="char:target"),
            )
            return _get_live(start.handle)

        live = run_async(_run())
        rolled = next(e for e in events_of(live, SaveRolled) if e.target_id == "char:target")
        assert rolled.succeeded is True
        applied = [e for e in events_of(live, ConditionApplied) if e.target_id == "char:target"]
        assert not any(e.condition == "grappled" for e in applied)


class TestEscapeGrapple:
    def test_escape_uses_stored_dc_and_ends_condition_on_success(self):
        """(d) ``escape_grapple`` rolls a check against the STORED escape DC
        (mutating the brute's Strength afterward doesn't move it); success
        removes Grappled and ends the escaper's turn."""

        async def _run():
            start = await _start_grapple_combat("t6-d-escape-success")
            live = _get_live(start.handle)
            for idx, c in enumerate(live.initiative):
                if c.entity_id == "char:target":
                    live.initiative[idx] = c.model_copy(update={"strength": 1, "dexterity": 1})
                    break
            await submit_player_intent(
                start.handle,
                actor_id="char:brute",
                intent=PlayerIntent(intent_type="grapple", target_id="char:target"),
            )
            live = _get_live(start.handle)
            assert live.current_actor_id == "char:target"
            # Mutate the brute's Strength on the live slot AFTER the grapple —
            # if escape recomputed the DC, this would move it off 15.
            for idx, c in enumerate(live.initiative):
                if c.entity_id == "char:brute":
                    live.initiative[idx] = c.model_copy(update={"strength": 3})
                    break
            # Huge STR/DEX guarantees the escape check succeeds.
            for idx, c in enumerate(live.initiative):
                if c.entity_id == "char:target":
                    live.initiative[idx] = c.model_copy(update={"strength": 30, "dexterity": 30})
                    break
            await submit_player_intent(
                start.handle,
                actor_id="char:target",
                intent=PlayerIntent(intent_type="escape_grapple"),
            )
            return _get_live(start.handle)

        live = run_async(_run())
        rolled = next(e for e in events_of(live, CheckRolled) if e.actor_id == "char:target")
        assert rolled.ability in ("str", "dex")
        assert rolled.dc == 15
        removed = [e for e in events_of(live, ConditionRemoved) if e.target_id == "char:target"]
        assert any(e.condition == "grappled" for e in removed)
        from dnd5e_engine.orchestrator import _effective_speed

        target = _find_combatant(live, "char:target")
        assert target is not None
        assert not any(ac.condition == "grappled" for ac in target.conditions)
        assert _effective_speed(target) > 0

    def test_escape_check_applies_the_exhaustion_penalty(self):
        """Fix round 1 — SRD 5.2 Exhaustion: "the roll is reduced by 2 times
        your Exhaustion level" on EVERY D20 Test, ability checks included
        (``rules/conditions.py::d20_test_penalty``). The grapple SAVE already
        threads this (mirroring ``_run_end_of_turn_saves``); the escape
        CHECK must too. Compares an exhausted escaper's ``CheckRolled.modifier``
        against an unexhausted control run of the identical scenario/seed —
        seed-independent, since both runs draw the same d20 stream and only
        the reported flat ``modifier`` should differ by ``-2 x level``.
        """

        async def _run(*, exhaustion_level: int | None):
            start = await _start_grapple_combat("t6-f-escape-exhaustion", rng_seed=11)
            live = _get_live(start.handle)
            for idx, c in enumerate(live.initiative):
                if c.entity_id == "char:target":
                    live.initiative[idx] = c.model_copy(update={"strength": 1, "dexterity": 1})
                    break
            await submit_player_intent(
                start.handle,
                actor_id="char:brute",
                intent=PlayerIntent(intent_type="grapple", target_id="char:target"),
            )
            live = _get_live(start.handle)
            if exhaustion_level is not None:
                target = _find_combatant(live, "char:target")
                assert target is not None
                for idx, c in enumerate(live.initiative):
                    if c.entity_id == "char:target":
                        live.initiative[idx] = c.model_copy(
                            update={
                                "conditions": [
                                    *c.conditions,
                                    ActiveCondition(
                                        condition="exhaustion",
                                        source_entity_id="implied:scenario",
                                        scope="combat",
                                        exhaustion_level=exhaustion_level,
                                    ),
                                ]
                            }
                        )
                        break
            await submit_player_intent(
                start.handle,
                actor_id="char:target",
                intent=PlayerIntent(intent_type="escape_grapple"),
            )
            live = _get_live(start.handle)
            return next(e for e in events_of(live, CheckRolled) if e.actor_id == "char:target")

        plain = run_async(_run(exhaustion_level=None))
        tired = run_async(_run(exhaustion_level=2))
        assert plain.modifier is not None
        assert tired.modifier is not None
        assert tired.modifier == plain.modifier - 2 * 2

    def test_escape_grapple_without_the_condition_is_rejected(self):
        """(d) An actor without Grappled cannot ``escape_grapple``."""

        async def _run():
            start = await _start_grapple_combat("t6-d-escape-not-grappled")
            with pytest.raises(IntentRejectedError) as exc_info:
                await submit_player_intent(
                    start.handle,
                    actor_id="char:brute",
                    intent=PlayerIntent(intent_type="escape_grapple"),
                )
            return exc_info

        exc_info = run_async(_run())
        assert exc_info.value.reason == "target_invalid"


class TestGrappleAutoReleaseOnIncapacitatedGrappler:
    def test_grapple_releases_when_grappler_becomes_incapacitated(self):
        """(e) SRD "Ending a Grapple" — the condition also ends if the
        grappler has the Incapacitated condition."""

        async def _run():
            start = await _start_grapple_combat("t6-e-auto-release")
            live = _get_live(start.handle)
            for idx, c in enumerate(live.initiative):
                if c.entity_id == "char:target":
                    live.initiative[idx] = c.model_copy(update={"strength": 1, "dexterity": 1})
                    break
            await submit_player_intent(
                start.handle,
                actor_id="char:brute",
                intent=PlayerIntent(intent_type="grapple", target_id="char:target"),
            )
            live = _get_live(start.handle)
            assert any(
                e.condition == "grappled"
                for e in events_of(live, ConditionApplied)
                if e.target_id == "char:target"
            )
            _emit(live, ConditionApplied(target_id="char:brute", condition="stunned"))
            return _get_live(start.handle)

        live = run_async(_run())
        removed = [e for e in events_of(live, ConditionRemoved) if e.target_id == "char:target"]
        assert any(e.condition == "grappled" for e in removed)
        target = _find_combatant(live, "char:target")
        assert target is not None
        assert not any(ac.condition == "grappled" for ac in target.conditions)


# ── C14 Task 7 — Shove and Stand Up ──────────────────────────────────────
#
# SRD 5.2 (Unarmed Strike, "Shove"): "The target must succeed on a Strength
# or Dexterity saving throw (it chooses which), or you either push it 5 feet
# away or cause it to have the Prone condition. The DC for the saving throw
# equals 8 plus your Strength modifier and Proficiency Bonus."
#
# SRD 5.2 (Prone, "Restricted Movement"): "you can spend an amount of
# movement equal to half your Speed (round down) to right yourself and
# thereby end the condition. If your Speed is 0, you can't right yourself."


class TestShoveSave:
    def test_shove_within_reach_defaults_to_prone_on_failed_save(self):
        """(a) A failed Shove save (default intent, no ``shove_push``)
        applies Prone, not a forced move, and ends the turn."""

        async def _run():
            start = await _start_grapple_combat("t7-a-shove-prone")
            live = _get_live(start.handle)
            for idx, c in enumerate(live.initiative):
                if c.entity_id == "char:target":
                    live.initiative[idx] = c.model_copy(update={"strength": 1, "dexterity": 1})
                    break
            await submit_player_intent(
                start.handle,
                actor_id="char:brute",
                intent=PlayerIntent(intent_type="shove", target_id="char:target"),
            )
            return _get_live(start.handle)

        live = run_async(_run())
        rolled = next(e for e in events_of(live, SaveRolled) if e.target_id == "char:target")
        assert rolled.dc == 15
        assert rolled.succeeded is False
        applied = [e for e in events_of(live, ConditionApplied) if e.target_id == "char:target"]
        assert any(e.condition == "prone" for e in applied)
        assert not events_of(live, CombatantMoved)
        assert live.current_actor_id != "char:brute"

    def test_shove_push_moves_the_target_5ft_with_no_prone(self):
        """(a) ``shove_push=True`` on a failed save pushes the target 5 ft
        away via ``push_combatant`` (``CombatantMoved(forced=True)``) and
        applies NO Prone condition."""

        async def _run():
            start = await _start_grapple_combat("t7-a-shove-push")
            live = _get_live(start.handle)
            for idx, c in enumerate(live.initiative):
                if c.entity_id == "char:target":
                    live.initiative[idx] = c.model_copy(update={"strength": 1, "dexterity": 1})
                    break
            await submit_player_intent(
                start.handle,
                actor_id="char:brute",
                intent=PlayerIntent(intent_type="shove", target_id="char:target", shove_push=True),
            )
            return _get_live(start.handle)

        live = run_async(_run())
        rolled = next(e for e in events_of(live, SaveRolled) if e.target_id == "char:target")
        assert rolled.succeeded is False
        moved = [e for e in events_of(live, CombatantMoved) if e.actor_id == "char:target"]
        assert moved
        assert moved[0].forced is True
        assert moved[0].distance_ft == 5
        applied = [e for e in events_of(live, ConditionApplied) if e.target_id == "char:target"]
        assert not any(e.condition == "prone" for e in applied)


class TestShoveRange:
    def test_shove_beyond_5ft_is_rejected_with_no_roll(self):
        """Same reach gate as Grapple: a target beyond 5 ft is rejected with
        no d20 drawn and no state change."""

        async def _run():
            start = await _start_grapple_combat("t7-shove-out-of-range", target_zone=cell(9, 0))
            with pytest.raises(IntentRejectedError) as exc_info:
                await submit_player_intent(
                    start.handle,
                    actor_id="char:brute",
                    intent=PlayerIntent(intent_type="shove", target_id="char:target"),
                )
            return exc_info, _get_live(start.handle)

        exc_info, live = run_async(_run())
        assert exc_info.value.reason == "target_invalid"
        assert not events_of(live, SaveRolled)
        brute = next(c for c in live.initiative if c.entity_id == "char:brute")
        assert brute.action_available is True


class TestStandUp:
    def test_stand_up_costs_half_speed_and_keeps_the_turn(self):
        """(b) Standing up from Prone with a full movement budget spends
        half Speed (rounded down), removes Prone, and keeps the actor on
        turn with the Action untouched."""

        async def _run():
            start = await _start_grapple_combat("t7-b-stand-up")
            live = _get_live(start.handle)
            await submit_player_intent(
                start.handle, actor_id="char:brute", intent=PlayerIntent(intent_type="pass")
            )
            live = _get_live(start.handle)
            _emit(live, ConditionApplied(target_id="char:target", condition="prone"))
            await submit_player_intent(
                start.handle,
                actor_id="char:target",
                intent=PlayerIntent(intent_type="stand_up"),
            )
            return _get_live(start.handle)

        live = run_async(_run())
        removed = [e for e in events_of(live, ConditionRemoved) if e.target_id == "char:target"]
        assert any(e.condition == "prone" for e in removed)
        target = _find_combatant(live, "char:target")
        assert target is not None
        assert not any(ac.condition == "prone" for ac in target.conditions)
        # Default base_speed 30 -> half Speed 15 spent, 15 left.
        assert target.movement_remaining == 15
        assert target.action_available is True
        assert live.current_actor_id == "char:target"

    def test_stand_up_while_not_prone_is_rejected(self):
        """(c) An actor without Prone has nothing to stand up from."""

        async def _run():
            start = await _start_grapple_combat("t7-c-stand-up-not-prone")
            await submit_player_intent(
                start.handle, actor_id="char:brute", intent=PlayerIntent(intent_type="pass")
            )
            with pytest.raises(IntentRejectedError) as exc_info:
                await submit_player_intent(
                    start.handle,
                    actor_id="char:target",
                    intent=PlayerIntent(intent_type="stand_up"),
                )
            return exc_info

        exc_info = run_async(_run())
        assert exc_info.value.reason == "target_invalid"

    def test_stand_up_with_speed_zero_is_rejected(self):
        """(c) Speed 0 (Grappled + Prone) — SRD 5.2 "If your Speed is 0,
        you can't right yourself.\""""

        async def _run():
            start = await _start_grapple_combat("t7-c-stand-up-speed-zero")
            await submit_player_intent(
                start.handle, actor_id="char:brute", intent=PlayerIntent(intent_type="pass")
            )
            live = _get_live(start.handle)
            _emit(live, ConditionApplied(target_id="char:target", condition="grappled"))
            _emit(live, ConditionApplied(target_id="char:target", condition="prone"))
            assert _effective_speed(_find_combatant(live, "char:target")) == 0
            with pytest.raises(IntentRejectedError) as exc_info:
                await submit_player_intent(
                    start.handle,
                    actor_id="char:target",
                    intent=PlayerIntent(intent_type="stand_up"),
                )
            return exc_info, _get_live(start.handle)

        exc_info, live = run_async(_run())
        assert exc_info.value.reason == "speed_zero"
        target = _find_combatant(live, "char:target")
        assert target is not None
        assert any(ac.condition == "prone" for ac in target.conditions)

    def test_stand_up_with_insufficient_movement_is_rejected_and_prone_persists(self):
        """(c) Insufficient remaining movement (< half Speed) rejects and
        leaves Prone in place."""

        async def _run():
            start = await _start_grapple_combat("t7-c-stand-up-insufficient")
            await submit_player_intent(
                start.handle, actor_id="char:brute", intent=PlayerIntent(intent_type="pass")
            )
            live = _get_live(start.handle)
            _emit(live, ConditionApplied(target_id="char:target", condition="prone"))
            for idx, c in enumerate(live.initiative):
                if c.entity_id == "char:target":
                    live.initiative[idx] = c.model_copy(update={"movement_remaining": 5})
                    break
            with pytest.raises(IntentRejectedError) as exc_info:
                await submit_player_intent(
                    start.handle,
                    actor_id="char:target",
                    intent=PlayerIntent(intent_type="stand_up"),
                )
            return exc_info, _get_live(start.handle)

        exc_info, live = run_async(_run())
        assert exc_info.value.reason == "insufficient_movement"
        target = _find_combatant(live, "char:target")
        assert target is not None
        assert any(ac.condition == "prone" for ac in target.conditions)
        assert target.movement_remaining == 5
