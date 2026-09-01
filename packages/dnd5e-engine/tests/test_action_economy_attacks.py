"""C14 Task 1 — Extra Attack counter and turn-keeping main-hand attacks.

SRD 5.2 (Fighter, Extra Attack): "You can attack twice, instead of once,
whenever you take the Attack action on your turn." The multiclass
non-stacking rule means the single highest-count qualifying feature sets
the cap (counts never sum): ``extra-attack`` -> 2, ``two-extra-attacks``
-> 3, ``three-extra-attacks`` -> 4.

``_attacks_per_action`` is the pure-ish lookup (reads the lib loader via
``_granted_feature_slugs``); the orchestrator-level behavior (turn-keeping
attack intents, the ``no_action_economy`` reject, back-compat for
1-attack actors) is exercised end-to-end via ``submit_player_intent``.
"""

from __future__ import annotations

import asyncio
import random

import pytest
from dnd5e_srd_data.loader import BundledAssetLoader

from dnd5e_engine import PlayerIntent, get_live
from dnd5e_engine.events import AttackFailed, AttackRolled, DamageApplied
from dnd5e_engine.lib_loader import set_lib_loader_for_tests
from dnd5e_engine.orchestrator import (
    IntentRejectedError,
    _attacks_per_action,
    _get_live,
    _twf_window_open,
    start_combat,
    submit_player_intent,
)
from dnd5e_engine.specs import EncounterMemberSpec, PartyMemberSpec
from dnd5e_engine.types.combat import Combatant
from tests.e2e.harness import cell, grid_scene


@pytest.fixture(autouse=True)
def _reset_lib_loader():
    set_lib_loader_for_tests(BundledAssetLoader())
    yield
    set_lib_loader_for_tests(None)


def _combatant(**overrides: object) -> Combatant:
    base = dict(
        entity_id="char:pc",
        entity_type="Character",
        name="PC",
        initiative=10,
        hp_current=20,
        hp_max=20,
    )
    base.update(overrides)
    return Combatant(**base)  # type: ignore[arg-type]


class TestAttacksPerAction:
    def test_fighter_level_5_gets_two_attacks(self):
        c = _combatant(class_slug="fighter", character_level=5)
        assert _attacks_per_action(c) == 2

    def test_fighter_level_4_gets_one_attack(self):
        c = _combatant(class_slug="fighter", character_level=4)
        assert _attacks_per_action(c) == 1

    def test_no_class_slug_gets_one_attack(self):
        c = _combatant(class_slug=None, character_level=20)
        assert _attacks_per_action(c) == 1

    def test_fighter_level_11_gets_three_attacks_never_five(self):
        """Multiclass non-stacking: level 11 Fighter grants BOTH
        ``extra-attack`` (2) and ``two-extra-attacks`` (3); the highest
        tier wins — the counts are never summed to 2 + 3 = 5."""
        c = _combatant(class_slug="fighter", character_level=11)
        assert _attacks_per_action(c) == 3


def _fighter_party(*, character_level: int = 5) -> list[PartyMemberSpec]:
    return [
        PartyMemberSpec(
            entity_id="char:ftr",
            name="Fighter",
            initiative=20,
            hp_current=40,
            hp_max=40,
            strength=16,
            attack_bonus=7,
            character_level=character_level,
            class_slug="fighter",
            zone_id=cell(0, 0),
        )
    ]


def _dummy_encounter() -> list[EncounterMemberSpec]:
    return [
        EncounterMemberSpec(
            entity_id="mon:dummy",
            entity_type="Monster",
            name="Dummy",
            initiative=1,
            hp_current=500,
            hp_max=500,
            ac=1,
            zone_id=cell(1, 0),
        )
    ]


async def _start_fighter_combat(session_id: str, *, character_level: int = 5):
    return await start_combat(
        session_id=session_id,
        party=_fighter_party(character_level=character_level),
        encounter=_dummy_encounter(),
        scene_zones=None,
        grid_scene=grid_scene(),
        rng_seed=21,
    )


def _attack_intent() -> PlayerIntent:
    return PlayerIntent(intent_type="attack", weapon_id="longsword", target_id="mon:dummy")


def test_extra_attack_view_shows_two_at_turn_start():
    async def _run():
        start = await _start_fighter_combat("sess-t1-view-start")
        return get_live(start.handle)

    view = asyncio.run(_run())
    assert view.turn.attacks_remaining == 2


def test_extra_attack_view_decrements_after_one_swing():
    async def _run():
        start = await _start_fighter_combat("sess-t1-view-decrement")
        await submit_player_intent(start.handle, actor_id="char:ftr", intent=_attack_intent())
        return get_live(start.handle)

    view = asyncio.run(_run())
    assert view.turn.attacks_remaining == 1


def test_third_attack_is_rejected_and_actor_keeps_the_turn():
    async def _run():
        start = await _start_fighter_combat("sess-t1-third-swing")
        for _ in range(2):
            await submit_player_intent(start.handle, actor_id="char:ftr", intent=_attack_intent())
        # third swing this Action — budget is exhausted (2/2 spent).
        await submit_player_intent(start.handle, actor_id="char:ftr", intent=_attack_intent())
        return _get_live(start.handle)

    live = asyncio.run(_run())
    swings = [
        e for e in live.event_log if isinstance(e, AttackRolled) and e.attacker_id == "char:ftr"
    ]
    assert len(swings) == 2
    rejections = [
        e
        for e in live.event_log
        if isinstance(e, AttackFailed)
        and e.actor_id == "char:ftr"
        and e.reason == "no_action_economy"
    ]
    assert len(rejections) == 1
    # the fighter still holds initiative — no TurnEnded fired for them.
    assert live.current_actor_id == "char:ftr"


def test_one_attack_actor_ends_turn_on_first_swing_back_compat():
    """A 1-attack actor (no Extra Attack) swinging a non-Light weapon must
    still end the turn on the first attack — the back-compat bar for C14."""

    async def _run():
        start = await _start_fighter_combat("sess-t1-back-compat", character_level=4)
        await submit_player_intent(start.handle, actor_id="char:ftr", intent=_attack_intent())
        return _get_live(start.handle)

    live = asyncio.run(_run())
    assert live.current_actor_id != "char:ftr"


def test_dash_then_attack_is_rejected_hard_no_double_dip():
    """Fix round 1 — Action-economy double-dip: Dash (a turn-keeping Action
    intent) spends ``action_available`` without touching
    ``attacks_remaining``/``attack_action_engaged``. A same-turn attack
    intent that follows must still be gated on the Action itself for the
    FIRST swing (``attack_action_engaged`` False) — otherwise the actor
    gets a full Dash AND a full attack sequence out of one Action.

    Controller ruling: restore the pre-C14 hard gate for the first swing —
    ``IntentRejectedError("no_action_economy")``, byte-for-byte today's
    Dash-then-attack behavior — while ``attacks_remaining <= 0`` still
    keeps the C14 turn-keeping ``AttackFailed`` emit (S05 contract).
    """

    async def _dash_then_attack(handle):
        await submit_player_intent(
            handle, actor_id="char:ftr", intent=PlayerIntent(intent_type="dash")
        )
        await submit_player_intent(handle, actor_id="char:ftr", intent=_attack_intent())

    async def _setup():
        return await _start_fighter_combat("sess-t1-dash-then-attack")

    start = asyncio.run(_setup())

    with pytest.raises(IntentRejectedError) as exc_info:
        asyncio.run(_dash_then_attack(start.handle))
    assert exc_info.value.reason == "no_action_economy"

    live = _get_live(start.handle)
    swings = [
        e for e in live.event_log if isinstance(e, AttackRolled) and e.attacker_id == "char:ftr"
    ]
    assert swings == []
    # the fighter still holds initiative — the raise unwinds before any
    # turn-advance logic runs.
    assert live.current_actor_id == "char:ftr"


# ── C14 Task 2 — Two-weapon fighting via the Light property ────────────────
#
# SRD 5.2 (Light property): "When you take the Attack action on your turn
# and attack with a Light weapon that you're holding in one hand, you can
# use a Bonus Action to attack with a different Light weapon that you're
# holding in the other hand... you don't add your ability modifier to the
# extra attack's damage unless that modifier is negative."


class _ForcedRng(random.Random):
    """Deterministic stand-in for the live combat's seeded RNG: every d20
    draw lands on a fixed non-crit/non-fumble total that beats the dummy's
    AC 1; every other die (weapon damage) returns a fixed pip count. Swapped
    in for ``live.rng`` AFTER ``start_combat`` (which already consumed the
    real seeded RNG for initiative), so it never perturbs initiative order —
    only the attack/damage rolls these tests care about."""

    def __init__(self, die_pips: int) -> None:
        super().__init__()
        self._die_pips = die_pips

    def randint(self, a: int, b: int) -> int:
        if (a, b) == (1, 20):
            return 15  # guaranteed hit vs. AC 1, never a nat 1/20
        return self._die_pips


def _duelist_party(
    *,
    strength: int = 16,
    dexterity: int = 10,
    attack_bonus: int = 7,
    class_slug: str | None = None,
    character_level: int = 1,
) -> list[PartyMemberSpec]:
    return [
        PartyMemberSpec(
            entity_id="char:duelist",
            name="Duelist",
            initiative=20,
            hp_current=20,
            hp_max=20,
            strength=strength,
            dexterity=dexterity,
            attack_bonus=attack_bonus,
            class_slug=class_slug,
            character_level=character_level,
            zone_id=cell(0, 0),
        )
    ]


async def _start_duelist_combat(
    session_id: str,
    *,
    strength: int = 16,
    dexterity: int = 10,
    attack_bonus: int = 7,
    class_slug: str | None = None,
    character_level: int = 1,
):
    start = await start_combat(
        session_id=session_id,
        party=_duelist_party(
            strength=strength,
            dexterity=dexterity,
            attack_bonus=attack_bonus,
            class_slug=class_slug,
            character_level=character_level,
        ),
        encounter=_dummy_encounter(),
        scene_zones=None,
        grid_scene=grid_scene(),
        rng_seed=1,
    )
    # Swap in the forced RNG post-initiative so every attack/damage roll this
    # test drives is deterministic.
    _get_live(start.handle).rng = _ForcedRng(4)
    return start


def _shortsword_intent() -> PlayerIntent:
    return PlayerIntent(intent_type="attack", weapon_id="shortsword", target_id="mon:dummy")


def _dagger_intent() -> PlayerIntent:
    return PlayerIntent(intent_type="attack", weapon_id="dagger", target_id="mon:dummy")


def _longsword_intent() -> PlayerIntent:
    return PlayerIntent(intent_type="attack", weapon_id="longsword", target_id="mon:dummy")


class TestLightWeaponMainHandSwing:
    def test_shortsword_swing_records_light_slug_and_keeps_turn(self):
        async def _run():
            start = await _start_duelist_combat("sess-t2-mainhand-slug")
            await submit_player_intent(
                start.handle, actor_id="char:duelist", intent=_shortsword_intent()
            )
            return _get_live(start.handle)

        live = asyncio.run(_run())
        actor = next(c for c in live.initiative if c.entity_id == "char:duelist")
        assert actor.light_weapon_swing_slug == "shortsword"
        # SRD back-compat exception: a Light main-hand swing keeps the turn
        # open for the off-hand Bonus Action window even for a 1-attack actor.
        assert live.current_actor_id == "char:duelist"


class TestLightWeaponOffhandSwing:
    def test_offhand_dagger_resolves_as_bonus_action_no_attack_budget_spend(self):
        async def _run():
            start = await _start_duelist_combat("sess-t2-offhand-resolves")
            await submit_player_intent(
                start.handle, actor_id="char:duelist", intent=_shortsword_intent()
            )
            live_before = _get_live(start.handle)
            actor_before = next(c for c in live_before.initiative if c.entity_id == "char:duelist")
            await submit_player_intent(
                start.handle, actor_id="char:duelist", intent=_dagger_intent()
            )
            return _get_live(start.handle), actor_before

        live, actor_before = asyncio.run(_run())
        actor_after = next(c for c in live.initiative if c.entity_id == "char:duelist")
        assert actor_before.bonus_action_available is True
        assert actor_after.bonus_action_available is False
        assert actor_after.offhand_attack_spent is True
        # the off-hand swing spends the Bonus Action, never the per-Action
        # attack budget — attacks_remaining is unchanged by it.
        assert actor_after.attacks_remaining == actor_before.attacks_remaining

        dummy_damage = [e for e in live.event_log if isinstance(e, DamageApplied)]
        assert len(dummy_damage) == 2
        offhand = dummy_damage[-1]
        assert 1 <= offhand.amount <= 4


class TestLightWeaponMainActionPriority:
    """Fix round 1 (controller ruling): main-action swings take priority.

    An Extra-Attack actor with Attack-action budget remaining
    (``attacks_remaining > 0``) swinging a SECOND, different Light weapon is
    still an ordinary main-hand Attack-action swing — the off-hand
    classification must not preempt it — UNLESS the host explicitly asks
    for the Bonus Action swing now via ``intent.use_bonus_action``.
    """

    def test_second_light_swing_with_budget_remaining_is_a_main_swing(self):
        """Fighter-5 (2 attacks): shortsword then dagger, both Light and
        different slugs. The SECOND swing must resolve as an ordinary
        Attack-action swing (full positive ability mod, attacks_remaining
        decremented, Bonus Action untouched) — NOT the TWF off-hand swing.
        A THIRD swing with a different Light weapon (budget now exhausted)
        DOES resolve as the off-hand Bonus Action swing, with the mod
        suppressed.
        """

        async def _run():
            start = await _start_duelist_combat(
                "sess-t2-priority-main-swing", class_slug="fighter", character_level=5
            )
            await submit_player_intent(
                start.handle, actor_id="char:duelist", intent=_shortsword_intent()
            )
            live_after_1 = _get_live(start.handle)
            actor_after_1 = next(
                c for c in live_after_1.initiative if c.entity_id == "char:duelist"
            )

            await submit_player_intent(
                start.handle, actor_id="char:duelist", intent=_dagger_intent()
            )
            live_after_2 = _get_live(start.handle)
            actor_after_2 = next(
                c for c in live_after_2.initiative if c.entity_id == "char:duelist"
            )
            # Snapshot the event log NOW (before swing 3 appends more) — the
            # live combat's event_log is a shared mutable list, so a bare
            # reference captured here would silently pick up swing 3's
            # events too by the time this coroutine returns.
            events_after_2 = list(live_after_2.event_log)

            await submit_player_intent(
                start.handle, actor_id="char:duelist", intent=_shortsword_intent()
            )
            live_after_3 = _get_live(start.handle)
            actor_after_3 = next(
                c for c in live_after_3.initiative if c.entity_id == "char:duelist"
            )
            return events_after_2, actor_after_1, actor_after_2, actor_after_3

        events_after_2, actor_after_1, actor_after_2, actor_after_3 = asyncio.run(_run())

        # After swing 1 (shortsword, main-hand): budget decremented 2 -> 1,
        # light slug recorded, Bonus Action untouched.
        assert actor_after_1.attacks_remaining == 1
        assert actor_after_1.light_weapon_swing_slug == "shortsword"
        assert actor_after_1.bonus_action_available is True

        # After swing 2 (dagger, DIFFERENT Light weapon, budget still > 0
        # BEFORE this swing): must be classified as a MAIN swing, not the
        # off-hand — budget decremented 1 -> 0, Bonus Action still
        # untouched, offhand not spent, and its damage carries the FULL
        # positive ability mod (STR 16 -> +3; forced die pips = 4 -> 7).
        assert actor_after_2.attacks_remaining == 0
        assert actor_after_2.bonus_action_available is True
        assert actor_after_2.offhand_attack_spent is False
        # The recorded light slug advances to the latest MAIN-hand Light
        # swing (dagger) — it is not "sticky" to the first swing.
        assert actor_after_2.light_weapon_swing_slug == "dagger"
        dummy_damage = [e for e in events_after_2 if isinstance(e, DamageApplied)]
        assert len(dummy_damage) == 2
        second_swing_damage = dummy_damage[-1]
        assert second_swing_damage.amount == 7

        # After swing 3 (shortsword, different from the recorded "dagger"
        # slug, budget NOW exhausted): this one IS the off-hand Bonus
        # Action swing — spends the Bonus Action, mod suppressed (die pips
        # 4, no positive mod -> amount 4).
        assert actor_after_3.bonus_action_available is False
        assert actor_after_3.offhand_attack_spent is True
        assert actor_after_3.attacks_remaining == 0

    def test_use_bonus_action_true_forces_offhand_immediately_with_budget_left(self):
        """Same fighter, but the host explicitly interleaves the off-hand
        swing early via ``intent.use_bonus_action=True`` while
        ``attacks_remaining`` is still > 0: classified off-hand immediately
        — Bonus Action spent, ``attacks_remaining`` untouched, mod
        suppressed."""

        async def _run():
            start = await _start_duelist_combat(
                "sess-t2-priority-explicit-bonus", class_slug="fighter", character_level=5
            )
            await submit_player_intent(
                start.handle, actor_id="char:duelist", intent=_shortsword_intent()
            )
            await submit_player_intent(
                start.handle,
                actor_id="char:duelist",
                intent=PlayerIntent(
                    intent_type="attack",
                    weapon_id="dagger",
                    target_id="mon:dummy",
                    use_bonus_action=True,
                ),
            )
            return _get_live(start.handle)

        live = asyncio.run(_run())
        actor = next(c for c in live.initiative if c.entity_id == "char:duelist")
        assert actor.bonus_action_available is False
        assert actor.offhand_attack_spent is True
        # attacks_remaining is UNCHANGED by the explicit-bonus off-hand
        # swing — it was 1 after the first (main-hand) swing, budget
        # untouched by the off-hand path.
        assert actor.attacks_remaining == 1

        dummy_damage = [e for e in live.event_log if isinstance(e, DamageApplied)]
        assert len(dummy_damage) == 2
        offhand = dummy_damage[-1]
        # Mod suppressed: die pips 4, no positive mod added -> raw 4.
        assert offhand.amount == 4


class TestLightWeaponOffhandGateFailures:
    def test_offhand_same_weapon_slug_is_rejected_no_action_economy(self):
        async def _run():
            start = await _start_duelist_combat("sess-t2-offhand-same-weapon")
            await submit_player_intent(
                start.handle, actor_id="char:duelist", intent=_shortsword_intent()
            )
            # SAME weapon slug as the main-hand swing — never opens the
            # off-hand window (SRD requires "a different Light weapon").
            await submit_player_intent(
                start.handle, actor_id="char:duelist", intent=_shortsword_intent()
            )
            return _get_live(start.handle)

        live = asyncio.run(_run())
        rejections = [
            e
            for e in live.event_log
            if isinstance(e, AttackFailed)
            and e.actor_id == "char:duelist"
            and e.reason == "no_action_economy"
        ]
        assert len(rejections) == 1
        assert live.current_actor_id == "char:duelist"

    def test_offhand_with_no_prior_light_swing_is_rejected_no_action_economy(self):
        """A non-Light main-hand weapon never opens the TWF window at all —
        it does not even keep a 1-attack actor's turn open (R1's back-compat
        bar). Use a 2-attack (Extra Attack) actor swinging the longsword
        TWICE so the turn stays open on its own multiattack budget; the
        THIRD (dagger) swing then hits the ``attacks_remaining <= 0`` gate
        with no light slug ever recorded — proving the rejection is the
        ``no_action_economy`` gate, not a same-weapon-slug artifact."""

        async def _run():
            start = await _start_duelist_combat(
                "sess-t2-offhand-no-light-window", class_slug="fighter", character_level=5
            )
            for _ in range(2):
                await submit_player_intent(
                    start.handle, actor_id="char:duelist", intent=_longsword_intent()
                )
            await submit_player_intent(
                start.handle, actor_id="char:duelist", intent=_dagger_intent()
            )
            return _get_live(start.handle)

        live = asyncio.run(_run())
        rejections = [
            e
            for e in live.event_log
            if isinstance(e, AttackFailed)
            and e.actor_id == "char:duelist"
            and e.reason == "no_action_economy"
        ]
        assert len(rejections) == 1
        assert live.current_actor_id == "char:duelist"

    def test_offhand_with_bonus_action_already_spent_is_rejected_no_action_economy(self):
        async def _run():
            start = await _start_duelist_combat("sess-t2-offhand-bonus-spent")
            await submit_player_intent(
                start.handle, actor_id="char:duelist", intent=_shortsword_intent()
            )
            live = _get_live(start.handle)
            # Simulate the Bonus Action already having been spent on
            # something else this turn (e.g. a bonus-action spell) — white-
            # box mutation of the live Combatant, mirroring the orchestrator's
            # own ``model_copy`` update pattern.
            for idx, c in enumerate(live.initiative):
                if c.entity_id == "char:duelist":
                    live.initiative[idx] = c.model_copy(update={"bonus_action_available": False})
                    break
            await submit_player_intent(
                start.handle, actor_id="char:duelist", intent=_dagger_intent()
            )
            return _get_live(start.handle)

        live = asyncio.run(_run())
        rejections = [
            e
            for e in live.event_log
            if isinstance(e, AttackFailed)
            and e.actor_id == "char:duelist"
            and e.reason == "no_action_economy"
        ]
        assert len(rejections) == 1
        assert live.current_actor_id == "char:duelist"


class TestLightWeaponNegativeAbilityMod:
    def test_offhand_negative_ability_mod_still_applies(self):
        """SRD 5.2 Light property: "...unless that modifier is negative" —
        a NEGATIVE governing-ability modifier is never suppressed, unlike a
        positive one. STR 6 -> mod -2; forced die pips=4 (``_ForcedRng``) ->
        raw damage 4, minus the applied -2 mod -> 2. No damage floor exists
        on this path (``apply.py::apply_damage`` never clamps a weapon
        swing's rolled total), so the exact value pins the real arithmetic
        rather than a floor convention.
        """

        async def _run():
            # Both STR and DEX lowered to -2: the shortsword/dagger are
            # Finesse weapons, whose governing ability is whichever of
            # STR/DEX is better for the attacker — pin BOTH negative so the
            # finesse pick can't smuggle in a DEX-10 (+0) mod instead.
            start = await _start_duelist_combat(
                "sess-t2-offhand-negative-mod", strength=6, dexterity=6, attack_bonus=7
            )
            await submit_player_intent(
                start.handle, actor_id="char:duelist", intent=_shortsword_intent()
            )
            await submit_player_intent(
                start.handle, actor_id="char:duelist", intent=_dagger_intent()
            )
            return _get_live(start.handle)

        live = asyncio.run(_run())
        dummy_damage = [e for e in live.event_log if isinstance(e, DamageApplied)]
        assert len(dummy_damage) == 2
        offhand = dummy_damage[-1]
        assert offhand.amount == 2


class TestTwfWindowOpen:
    """Prior-review follow-up (Task 1 had no direct unit test for
    ``_twf_window_open``): pins the window-open/closed truth table now that
    all three of its consulted fields are real, orchestrator-written state."""

    def test_window_closed_with_no_light_swing_recorded(self):
        c = _combatant(light_weapon_swing_slug=None, offhand_attack_spent=False)
        assert _twf_window_open(c) is False

    def test_window_open_after_a_light_main_hand_swing(self):
        c = _combatant(
            light_weapon_swing_slug="shortsword",
            offhand_attack_spent=False,
            bonus_action_available=True,
        )
        assert _twf_window_open(c) is True

    def test_window_closed_once_offhand_attack_spent(self):
        c = _combatant(
            light_weapon_swing_slug="shortsword",
            offhand_attack_spent=True,
            bonus_action_available=True,
        )
        assert _twf_window_open(c) is False

    def test_window_closed_once_bonus_action_spent(self):
        c = _combatant(
            light_weapon_swing_slug="shortsword",
            offhand_attack_spent=False,
            bonus_action_available=False,
        )
        assert _twf_window_open(c) is False
