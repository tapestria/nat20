"""C14 Task 3 — the Dodge action.

SRD 5.2 (Dodge, rules-glossary): "until the start of your next turn, any
attack roll made against you has Disadvantage if you can see the attacker,
and you make Dexterity saving throws with Advantage. You lose these benefits
if you have the Incapacitated condition or if your Speed is 0."

The "if you can see the attacker" conjunct on the attack-disadvantage half is
DEFERRED to C16b (no vision model wired to this seam yet) — see the comment
in ``activities/attack.py``.

Tasks 4-5 (Help / Hide) append their own test classes to this module.
"""

from __future__ import annotations

from dnd5e_engine import PlayerIntent
from dnd5e_engine.events import AttackRolled, SaveRolled
from dnd5e_engine.orchestrator import (
    _get_live,
    advance_monster_turn,
    start_combat,
    submit_player_intent,
)
from dnd5e_engine.specs import EncounterMemberSpec, PartyMemberSpec
from dnd5e_engine.types.conditions import ActiveCondition
from tests.e2e.harness import cell, events_of, grid_scene, run_async


def _dodge_party(**overrides: object) -> list[PartyMemberSpec]:
    base = dict(
        entity_id="char:dodger",
        name="Dodger",
        initiative=20,
        hp_current=30,
        hp_max=30,
        ac=14,
        dexterity=14,
        zone_id=cell(0, 0),
    )
    base.update(overrides)
    return [PartyMemberSpec(**base)]  # type: ignore[arg-type]


def _foe_encounter(**overrides: object) -> list[EncounterMemberSpec]:
    base = dict(
        entity_id="mon:foe",
        entity_type="Monster",
        name="Foe",
        initiative=10,
        hp_current=30,
        hp_max=30,
        ac=10,
        attack_bonus=5,
        zone_id=cell(1, 0),
    )
    base.update(overrides)
    return [EncounterMemberSpec(**base)]  # type: ignore[arg-type]


async def _start_dodge_combat(session_id: str, **party_overrides: object):
    return await start_combat(
        session_id=session_id,
        party=_dodge_party(**party_overrides),
        encounter=_foe_encounter(),
        scene_zones=None,
        grid_scene=grid_scene(),
        rng_seed=7,
    )


def _set_condition(live, entity_id: str, condition: str) -> None:
    for idx, c in enumerate(live.initiative):
        if c.entity_id == entity_id:
            live.initiative[idx] = c.model_copy(
                update={
                    "conditions": [
                        ActiveCondition(
                            condition=condition,
                            source_entity_id="implied:scenario",
                            scope="combat",
                        )
                    ]
                }
            )
            return
    raise AssertionError(f"{entity_id} not found in initiative")


class TestDodgeStateAndTurnKeeping:
    def test_dodge_sets_flag_consumes_action_and_ends_turn(self):
        """(a) A ``dodge`` intent sets ``dodging`` True, consumes the Action,
        and ends the turn immediately (no activity resolution)."""

        async def _run():
            start = await _start_dodge_combat("t3-a-dodge-state")
            await submit_player_intent(
                start.handle,
                actor_id="char:dodger",
                intent=PlayerIntent(intent_type="dodge"),
            )
            return _get_live(start.handle)

        live = run_async(_run())
        dodger = next(c for c in live.initiative if c.entity_id == "char:dodger")
        assert dodger.dodging is True
        assert dodger.action_available is False
        # Turn already advanced past the dodger — the monster is up.
        assert live.current_actor_id == "mon:foe"


class TestDodgeAttackDisadvantage:
    def test_attack_against_a_dodging_target_is_disadvantaged(self):
        """(b) A monster attack against a dodging target rolls with
        disadvantage and names "dodge" among the sources."""

        async def _run():
            start = await _start_dodge_combat("t3-b-attack-disadvantage")
            await submit_player_intent(
                start.handle,
                actor_id="char:dodger",
                intent=PlayerIntent(intent_type="dodge"),
            )
            await advance_monster_turn(start.handle)
            return _get_live(start.handle)

        live = run_async(_run())
        rolled = next(e for e in events_of(live, AttackRolled) if e.target_id == "char:dodger")
        assert rolled.advantage == "disadvantage"
        assert "dodge" in rolled.sources

    def test_dodge_benefit_lapses_at_the_start_of_the_dodgers_next_turn(self):
        """(c) "until the start of your next turn" — the flag (and therefore
        the attack disadvantage) lapses once the dodger's own next turn
        begins."""

        async def _run():
            start = await _start_dodge_combat("t3-c-lapse")
            await submit_player_intent(
                start.handle,
                actor_id="char:dodger",
                intent=PlayerIntent(intent_type="dodge"),
            )
            # The monster's turn resolves synchronously into the dodger's own
            # next TurnStarted (``_end_turn_and_advance`` -> ``_begin_turn``),
            # which is the exact SRD expiry point — no further intent needed.
            await advance_monster_turn(start.handle)
            return _get_live(start.handle)

        live = run_async(_run())
        dodger = next(c for c in live.initiative if c.entity_id == "char:dodger")
        assert dodger.dodging is False
        assert live.current_actor_id == "char:dodger"

    def test_incapacitated_dodger_grants_no_disadvantage(self):
        """(d) SRD loss clause — Incapacitated strips the Dodge benefit even
        though the dodger did take the Dodge action this turn."""

        async def _run():
            start = await _start_dodge_combat("t3-d-incapacitated")
            await submit_player_intent(
                start.handle,
                actor_id="char:dodger",
                intent=PlayerIntent(intent_type="dodge"),
            )
            live = _get_live(start.handle)
            _set_condition(live, "char:dodger", "incapacitated")
            await advance_monster_turn(start.handle)
            return live

        live = run_async(_run())
        rolled = next(e for e in events_of(live, AttackRolled) if e.target_id == "char:dodger")
        assert rolled.advantage == "normal"
        assert "dodge" not in rolled.sources

    def test_speed_zero_dodger_grants_no_disadvantage(self):
        """(d) SRD loss clause — a grappled (Speed 0) dodger loses the
        attack-disadvantage benefit."""

        async def _run():
            start = await _start_dodge_combat("t3-d-speed-zero")
            await submit_player_intent(
                start.handle,
                actor_id="char:dodger",
                intent=PlayerIntent(intent_type="dodge"),
            )
            live = _get_live(start.handle)
            _set_condition(live, "char:dodger", "grappled")
            await advance_monster_turn(start.handle)
            return live

        live = run_async(_run())
        rolled = next(e for e in events_of(live, AttackRolled) if e.target_id == "char:dodger")
        assert rolled.advantage == "normal"
        assert "dodge" not in rolled.sources


class TestDodgeDexSaveAdvantage:
    def test_dodging_target_rolls_dex_saves_with_advantage(self):
        """(e) "you make Dexterity saving throws with Advantage" — drive a
        DEX-save spell (Acid Splash) against a dodging foe."""

        async def _run():
            start = await start_combat(
                session_id="t3-e-dex-save-advantage",
                party=[
                    PartyMemberSpec(
                        entity_id="char:cleric",
                        name="Cleric",
                        initiative=20,
                        hp_current=20,
                        hp_max=20,
                        spells_known=["acid-splash"],
                        character_level=1,
                        zone_id=cell(0, 0),
                    )
                ],
                encounter=[
                    EncounterMemberSpec(
                        entity_id="mon:foe",
                        entity_type="Monster",
                        name="Foe",
                        initiative=1,
                        hp_current=20,
                        hp_max=20,
                        ac=12,
                        dexterity=10,
                        zone_id=cell(1, 0),
                    )
                ],
                scene_zones=None,
                grid_scene=grid_scene(),
                rng_seed=13,
            )
            live = _get_live(start.handle)
            # ``dodging`` is a plain Combatant flag, not a condition — set it
            # directly (mirrors the SRD result of a prior ``dodge`` intent).
            for idx, c in enumerate(live.initiative):
                if c.entity_id == "mon:foe":
                    live.initiative[idx] = c.model_copy(update={"dodging": True})
                    break
            await submit_player_intent(
                start.handle,
                actor_id="char:cleric",
                intent=PlayerIntent(
                    intent_type="cast_spell", spell_id="acid-splash", target_id="mon:foe"
                ),
            )
            return live

        live = run_async(_run())
        rolled = next(e for e in events_of(live, SaveRolled) if e.target_id == "mon:foe")
        assert rolled.ability == "dex"
        assert rolled.advantage == "advantage"
