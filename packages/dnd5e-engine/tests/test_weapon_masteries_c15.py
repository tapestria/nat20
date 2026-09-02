"""C15 Task 6 — Vex and Sap weapon-mastery riders; Topple honors condition
immunity (closes e2e scenario C15-S07, ``tests/e2e/test_c15_attack_rules.py``).

SRD 5.2 verbatim (Appendix D, Weapon Mastery / Immunity):

* **Vex** — "If you hit a creature with this weapon and deal damage to the
  creature, you have Advantage on your next attack roll against that
  creature before the end of your next turn."
* **Sap** — "If you hit a creature with this weapon, that creature has
  Disadvantage on its next attack roll before the start of your next turn."
* **Immunity** — "Immunity to a condition means you aren't affected by it."
  The save still rolls; only the resulting condition APPLICATION is gated.

Pure-resolver tests ((c) vex zero-damage no-proc, (e) topple immunity) mirror
``tests/test_versatile_and_attribution.py``'s direct ``resolve_activity``
pattern. Orchestrator-level tests ((a) per-target gating, (b) expiry,
(d) sap consumption/expiry) mirror ``tests/test_dodge_help_hide.py``'s
live-state-peeking pattern — ``live.vex_grants`` / ``live.sap_marks`` are the
mastery analogues of ``live.help_grants``.

Task 7 (slow/push/nick/cleave) appends its own tests to this module.
"""

from __future__ import annotations

import random

from dnd5e_srd_data.loader import BundledAssetLoader

from dnd5e_engine import PlayerIntent
from dnd5e_engine.activities.context import ActivityResolutionContext
from dnd5e_engine.activities.resolver import resolve_activity
from dnd5e_engine.events import AttackRolled, ConditionApplied, SaveRolled
from dnd5e_engine.orchestrator import (
    _get_live,
    advance_monster_turn,
    start_combat,
    submit_player_intent,
)
from dnd5e_engine.specs import EncounterMemberSpec, PartyMemberSpec
from dnd5e_engine.types.combat import Combatant
from tests.e2e.harness import cell, events_of, grid_scene, run_async

_LOADER = BundledAssetLoader()

# shortsword mastery == "vex" (verified against the canonical corpus); mace
# mastery == "sap"; battleaxe mastery == "topple" — all three grepped from
# ``packages/dnd5e-srd-data/src/dnd5e_srd_data/canonical/items/*.json``.


# ---------------------------------------------------------------------------
# Pure-resolver level: (c) vex zero-damage no-proc, (e) topple immunity
# ---------------------------------------------------------------------------


def _hero(**overrides: object) -> Combatant:
    base: dict[str, object] = dict(
        entity_id="char:hero",
        entity_type="Character",
        name="Hero",
        initiative=10,
        hp_current=20,
        hp_max=20,
        strength=16,
        dexterity=16,
    )
    base.update(overrides)
    return Combatant(**base)  # type: ignore[arg-type]


def _foe(**overrides: object) -> Combatant:
    base: dict[str, object] = dict(
        entity_id="mon:foe",
        entity_type="Monster",
        name="Foe",
        initiative=1,
        hp_current=50,
        hp_max=50,
        ac=1,
    )
    base.update(overrides)
    return Combatant(**base)  # type: ignore[arg-type]


def test_c_vex_hit_dealing_zero_final_damage_does_not_proc() -> None:
    """(c) SRD Vex requires the hit to "deal damage to the creature". A
    damage-immune target takes ZERO final (post-immunity) damage from a
    vex-mastery hit — no proc is appended to ``ctx.mastery_procs``."""
    shortsword = _LOADER.get_weapon("shortsword")
    assert shortsword is not None
    assert shortsword.mastery == "vex"
    activity = next(a for a in shortsword.activities if a.kind == "attack")
    ctx = ActivityResolutionContext(
        rng=random.Random(1),
        caster=_hero(),
        targets=[_foe(damage_immunities=["piercing"])],
        event_emitter=lambda _ev: None,
        caster_abilities={"str": 16, "dex": 16, "con": 10, "int": 10, "wis": 10, "cha": 10},
        caster_proficiency_bonus=2,
        caster_level=1,
        variables={"force_d20": 15},
    )

    resolve_activity(activity, ctx, weapon=shortsword)

    assert ctx.mastery_procs == []


def test_c_vex_hit_dealing_real_damage_procs() -> None:
    """(c)-control: the SAME hit against a non-immune target DOES proc, so
    the zero-damage test above is pinning immunity, not a broken proc path."""
    shortsword = _LOADER.get_weapon("shortsword")
    assert shortsword is not None
    activity = next(a for a in shortsword.activities if a.kind == "attack")
    ctx = ActivityResolutionContext(
        rng=random.Random(1),
        caster=_hero(),
        targets=[_foe()],
        event_emitter=lambda _ev: None,
        caster_abilities={"str": 16, "dex": 16, "con": 10, "int": 10, "wis": 10, "cha": 10},
        caster_proficiency_bonus=2,
        caster_level=1,
        variables={"force_d20": 15},
    )

    resolve_activity(activity, ctx, weapon=shortsword)

    assert ctx.mastery_procs == [("vex", "mon:foe")]


def test_e_topple_save_still_rolls_but_prone_is_suppressed_by_immunity() -> None:
    """(e) The immunity-gate fix: ``SaveRolled`` still fires against a
    prone-immune target (the save always rolls); ``ConditionApplied`` does
    NOT (the emit is what's gated)."""
    battleaxe = _LOADER.get_weapon("battleaxe")
    assert battleaxe is not None
    assert battleaxe.mastery == "topple"
    activity = next(a for a in battleaxe.activities if a.kind == "attack")
    events: list[object] = []
    ctx = ActivityResolutionContext(
        rng=random.Random(1),
        caster=_hero(),
        targets=[_foe(condition_immunities=["prone"])],
        event_emitter=events.append,
        caster_abilities={"str": 16, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10},
        caster_proficiency_bonus=2,
        caster_level=1,
        variables={"force_d20": 15, "force_save_d20": 1},
    )

    resolve_activity(activity, ctx, weapon=battleaxe)

    saves = [e for e in events if isinstance(e, SaveRolled)]
    conditions = [e for e in events if isinstance(e, ConditionApplied)]
    assert len(saves) == 1
    assert saves[0].succeeded is False  # forced natural 1 vs the DC
    assert conditions == []


def test_e_topple_still_applies_prone_when_the_target_is_not_immune() -> None:
    """(e)-control: the SAME failed save against a non-immune target DOES
    apply prone — pinning that the fix gates the emit, not the save."""
    battleaxe = _LOADER.get_weapon("battleaxe")
    assert battleaxe is not None
    activity = next(a for a in battleaxe.activities if a.kind == "attack")
    events: list[object] = []
    ctx = ActivityResolutionContext(
        rng=random.Random(1),
        caster=_hero(),
        targets=[_foe()],
        event_emitter=events.append,
        caster_abilities={"str": 16, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10},
        caster_proficiency_bonus=2,
        caster_level=1,
        variables={"force_d20": 15, "force_save_d20": 1},
    )

    resolve_activity(activity, ctx, weapon=battleaxe)

    conditions = [e for e in events if isinstance(e, ConditionApplied)]
    assert len(conditions) == 1
    assert conditions[0].condition == "prone"


class _MaxRandom(random.Random):
    """Deterministic stand-in RNG: every ``randint(a, b)`` draw returns ``b``
    (mirrors ``tests/test_versatile_and_attribution.py``), so a rolled die's
    size is unambiguous from the returned amount."""

    def randint(self, a: int, b: int) -> int:
        del a
        return b


def test_vex_advantage_feeds_the_same_boolean_sneak_attack_triggers_reads() -> None:
    """Vex synergy (recon note, C15 Task 6 brief): a vex-advantaged Finesse
    weapon swing can Sneak Attack even with NO flag-based
    ``attacker_has_advantage`` and no adjacent ally — ``attack.py`` folds
    ``ctx.attacker_vex_advantage`` into the SAME boolean
    ``sneak_attack_triggers`` reads."""
    shortsword = _LOADER.get_weapon("shortsword")
    assert shortsword is not None
    activity = next(a for a in shortsword.activities if a.kind == "attack")

    def _damage_dealt(*, vex: bool) -> int:
        events: list[object] = []
        ctx = ActivityResolutionContext(
            rng=_MaxRandom(),
            caster=_hero(),
            targets=[_foe()],
            event_emitter=events.append,
            caster_abilities={"str": 10, "dex": 16, "con": 10, "int": 10, "wis": 10, "cha": 10},
            caster_proficiency_bonus=2,
            caster_level=5,
            variables={"force_d20": 15},
            scale_values={"rogue.sneak-attack": "1d6"},
            attacker_vex_advantage={"mon:foe": True} if vex else {},
        )
        resolve_activity(activity, ctx, weapon=shortsword)
        from dnd5e_engine.events import DamageApplied

        return sum(e.amount for e in events if isinstance(e, DamageApplied))

    without_vex = _damage_dealt(vex=False)
    with_vex = _damage_dealt(vex=True)

    # 1d6 (max 6) sneak-attack rider fires ONLY when vex advantage is present.
    assert with_vex - without_vex == 6


# ---------------------------------------------------------------------------
# Orchestrator level: (a) per-target gating, (b) expiry, (d) sap
# ---------------------------------------------------------------------------

_PASS = PlayerIntent(intent_type="pass")


def _vex_attack(target_id: str) -> PlayerIntent:
    return PlayerIntent(intent_type="attack", weapon_id="shortsword", target_id=target_id)


async def _start_two_monster_combat(session_id: str):
    return await start_combat(
        session_id=session_id,
        party=[
            PartyMemberSpec(
                entity_id="char:hero",
                name="Hero",
                initiative=20,
                hp_current=20,
                hp_max=20,
                strength=16,
                dexterity=16,
                zone_id=cell(0, 0),
            )
        ],
        encounter=[
            EncounterMemberSpec(
                entity_id="mon:foe1",
                entity_type="Monster",
                name="Foe1",
                initiative=10,
                hp_current=500,
                hp_max=500,
                ac=1,
                zone_id=cell(0, 1),
            ),
            EncounterMemberSpec(
                entity_id="mon:foe2",
                entity_type="Monster",
                name="Foe2",
                initiative=5,
                hp_current=500,
                hp_max=500,
                ac=1,
                zone_id=cell(0, 2),
            ),
        ],
        scene_zones=None,
        grid_scene=grid_scene(),
        rng_seed=1,
    )


def test_a_vex_grant_applies_only_to_the_same_target() -> None:
    """(a) A shortsword (vex) hit + damage against ``mon:foe1`` grants
    Advantage on the hero's next attack roll vs the SAME target; the SAME
    setup attacking a DIFFERENT target next sees no benefit (per-target
    gating, ``ctx.attacker_vex_advantage`` keyed by target_id)."""

    def _run(second_target: str):
        async def _inner():
            start = await _start_two_monster_combat(f"c15-t6-a-{second_target}")
            live = _get_live(start.handle)
            await submit_player_intent(
                start.handle, actor_id="char:hero", intent=_vex_attack("mon:foe1")
            )
            # Shortsword is Light — the TWF window keeps the turn open (C14
            # economy); pass closes it (mirrors the S07 e2e repair).
            await submit_player_intent(start.handle, actor_id="char:hero", intent=_PASS)
            await advance_monster_turn(start.handle)  # mon:foe1
            await advance_monster_turn(start.handle)  # mon:foe2
            await submit_player_intent(
                start.handle, actor_id="char:hero", intent=_vex_attack(second_target)
            )
            return live

        return run_async(_inner())

    live_same = _run("mon:foe1")
    live_diff = _run("mon:foe2")

    same_swings = [e for e in events_of(live_same, AttackRolled) if e.attacker_id == "char:hero"]
    diff_swings = [e for e in events_of(live_diff, AttackRolled) if e.attacker_id == "char:hero"]
    assert len(same_swings) == 2
    assert same_swings[0].advantage == "normal"
    assert same_swings[1].advantage == "advantage"
    assert len(diff_swings) == 2
    assert diff_swings[0].advantage == "normal"
    assert diff_swings[1].advantage == "normal"  # different target — no grant


def test_b_vex_grant_survives_one_round_then_expires_unused() -> None:
    """(b) A vex grant issued on turn N survives the intervening monster
    round and is still live through the hero's turn N+1 ("before the end of
    your next turn"); if UNUSED through turn N+1, it lapses — a turn N+2
    attack vs the same target rolls normal."""

    async def _run():
        start = await _start_two_monster_combat("c15-t6-b")
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle, actor_id="char:hero", intent=_vex_attack("mon:foe1")
        )
        await submit_player_intent(start.handle, actor_id="char:hero", intent=_PASS)
        await advance_monster_turn(start.handle)  # mon:foe1
        await advance_monster_turn(start.handle)  # mon:foe2
        # Hero's turn N+1 — the grant is still live (rounds_remaining == 1)
        # but this turn passes WITHOUT attacking mon:foe1, so it is never
        # consumed and must lapse at THIS turn's end.
        await submit_player_intent(start.handle, actor_id="char:hero", intent=_PASS)
        await advance_monster_turn(start.handle)  # mon:foe1
        await advance_monster_turn(start.handle)  # mon:foe2
        # Hero's turn N+2 — the grant is gone; this attack rolls normal.
        await submit_player_intent(
            start.handle, actor_id="char:hero", intent=_vex_attack("mon:foe1")
        )
        return live

    live = run_async(_run())
    swings = [e for e in events_of(live, AttackRolled) if e.attacker_id == "char:hero"]
    assert len(swings) == 2
    assert swings[1].advantage == "normal"
    # The turn-N+2 attack landed a FRESH hit (foe1 has 500 HP), which procs
    # its OWN brand-new grant (rounds_remaining reset to 2) — this pins that
    # the OLD grant (from turn N) is gone by the time this roll happened,
    # not that vex_grants is permanently empty.
    assert live.vex_grants.get("char:hero") == {"mon:foe1": 2}


def test_d_sap_mark_gives_the_target_disadvantage_on_its_next_attack() -> None:
    """(d) A mace (sap) hit marks the TARGET; that creature's own next
    attack roll (regardless of weapon) is at Disadvantage — one-use, popped
    the moment it rolls."""

    async def _run():
        start = await start_combat(
            session_id="c15-t6-d-consumed",
            party=[
                PartyMemberSpec(
                    entity_id="char:sapper",
                    name="Sapper",
                    initiative=20,
                    hp_current=20,
                    hp_max=20,
                    strength=16,
                    ac=1,
                    zone_id=cell(0, 0),
                ),
                PartyMemberSpec(
                    entity_id="char:sapped",
                    name="Sapped",
                    initiative=15,
                    hp_current=20,
                    hp_max=20,
                    strength=16,
                    dexterity=16,
                    ac=1,
                    zone_id=cell(0, 1),
                ),
            ],
            encounter=[
                EncounterMemberSpec(
                    entity_id="mon:dummy",
                    entity_type="Monster",
                    name="Dummy",
                    initiative=1,
                    hp_current=500,
                    hp_max=500,
                    ac=1,
                    zone_id=cell(0, 2),
                )
            ],
            scene_zones=None,
            grid_scene=grid_scene(),
            rng_seed=2,
        )
        live = _get_live(start.handle)
        mace = _LOADER.get_weapon("mace")
        assert mace is not None
        assert mace.mastery == "sap"
        await submit_player_intent(
            start.handle,
            actor_id="char:sapper",
            intent=PlayerIntent(intent_type="attack", weapon_id="mace", target_id="char:sapped"),
        )
        # Mace is not Light — no TWF window, the turn ends without a pass.
        await submit_player_intent(
            start.handle,
            actor_id="char:sapped",
            intent=PlayerIntent(
                intent_type="attack", weapon_id="shortsword", target_id="mon:dummy"
            ),
        )
        return live

    live = run_async(_run())
    sapped_swing = next(e for e in events_of(live, AttackRolled) if e.attacker_id == "char:sapped")
    assert sapped_swing.advantage == "disadvantage"
    assert "char:sapped" not in live.sap_marks  # one-use pop


def test_d_sap_mark_expires_at_the_sappers_own_next_turn_start_if_unused() -> None:
    """(d) "before the start of your next turn" is the SOURCE ATTACKER's own
    next turn — an unconsumed mark lapses there even though the sapped
    creature never attacked."""

    async def _run():
        start = await start_combat(
            session_id="c15-t6-d-unconsumed",
            party=[
                PartyMemberSpec(
                    entity_id="char:sapper",
                    name="Sapper",
                    initiative=20,
                    hp_current=20,
                    hp_max=20,
                    strength=16,
                    ac=1,
                    zone_id=cell(0, 0),
                ),
                PartyMemberSpec(
                    entity_id="char:sapped",
                    name="Sapped",
                    initiative=15,
                    hp_current=20,
                    hp_max=20,
                    ac=1,
                    zone_id=cell(0, 1),
                ),
            ],
            encounter=[
                EncounterMemberSpec(
                    entity_id="mon:dummy",
                    entity_type="Monster",
                    name="Dummy",
                    initiative=1,
                    hp_current=500,
                    hp_max=500,
                    ac=1,
                    zone_id=cell(0, 2),
                )
            ],
            scene_zones=None,
            grid_scene=grid_scene(),
            rng_seed=3,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:sapper",
            intent=PlayerIntent(intent_type="attack", weapon_id="mace", target_id="char:sapped"),
        )
        await submit_player_intent(start.handle, actor_id="char:sapped", intent=_PASS)
        await advance_monster_turn(start.handle)  # mon:dummy — no template, auto-passes
        # Round-wrap back to char:sapper's own TurnStarted has already fired
        # by now (advance_monster_turn ends the dummy's turn unconditionally).
        return live

    live = run_async(_run())
    assert live.current_actor_id == "char:sapper"
    assert "char:sapped" not in live.sap_marks
