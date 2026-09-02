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


# ===========================================================================
# C15 Task 7 — Slow, Push, Cleave, Nick (completing all eight masteries)
# ===========================================================================
#
# SRD 5.2 verbatim (Appendix D, Weapon Mastery):
#
# * **Slow** — "If you hit a creature with this weapon and deal damage to it,
#   you can reduce its Speed by 10 feet until the start of your next turn. If
#   the creature is hit more than once by weapons that have this property,
#   the Speed reduction doesn't exceed 10 feet."
# * **Push** — "If you hit a creature with this weapon, you can push the
#   creature up to 10 feet straight away from yourself if it is Large or
#   smaller."
# * **Cleave** — "If you hit a creature with a melee attack roll using this
#   weapon, you can make a melee attack roll with the weapon against a second
#   creature within 5 feet of the first that is also within your reach. On a
#   hit, the second creature takes the weapon's damage, but don't add your
#   ability modifier to that damage unless that modifier is negative. You can
#   make this extra attack only once per turn."
# * **Nick** — "When you make the extra attack of the Light property, you can
#   make it as part of the Attack action instead of as a Bonus Action. You
#   can make this extra attack only once per turn."
#
# Corpus slugs (grepped from canonical/items/*.json ``"mastery"``): club /
# whip / javelin / longbow / light-crossbow / sling = slow; greatclub / pike /
# warhammer / heavy-crossbow = push; greataxe / halberd = cleave; scimitar /
# dagger / sickle / light-hammer = nick; shortsword = vex (the non-Nick
# off-hand control below).

from dnd5e_engine.events import AttackFailed, CombatantMoved, DamageApplied  # noqa: E402
from dnd5e_engine.orchestrator import _effective_speed  # noqa: E402


def _pc(entity_id: str, name: str, zone: str, **overrides: object) -> PartyMemberSpec:
    base: dict[str, object] = dict(
        entity_id=entity_id,
        name=name,
        initiative=20,
        hp_current=20,
        hp_max=20,
        strength=16,
        dexterity=16,
        ac=1,
        zone_id=zone,
    )
    base.update(overrides)
    return PartyMemberSpec(**base)  # type: ignore[arg-type]


def _mon(entity_id: str, name: str, zone: str, **overrides: object) -> EncounterMemberSpec:
    base: dict[str, object] = dict(
        entity_id=entity_id,
        entity_type="Monster",
        name=name,
        initiative=10,
        hp_current=500,
        hp_max=500,
        ac=1,
        zone_id=zone,
    )
    base.update(overrides)
    return EncounterMemberSpec(**base)  # type: ignore[arg-type]


def _combatant(live, entity_id: str) -> Combatant:
    return next(c for c in live.initiative if c.entity_id == entity_id)


def _attack(weapon_id: str, target_id: str, **kw: object) -> PlayerIntent:
    return PlayerIntent(intent_type="attack", weapon_id=weapon_id, target_id=target_id, **kw)  # type: ignore[arg-type]


async def _start(session_id: str, party, encounter, *, seed: int = 1):
    start = await start_combat(
        session_id=session_id,
        party=party,
        encounter=encounter,
        scene_zones=None,
        grid_scene=grid_scene(),
        rng_seed=seed,
    )
    live = _get_live(start.handle)
    # Every attack d20 lands a natural 20 (auto-hit, crit) and every damage
    # die rolls its maximum — the mastery riders under test all key off a
    # HIT, so the d20 must never fumble.
    live.rng = _MaxRandom()
    return start, live


# ── (a) Slow ─────────────────────────────────────────────────────────────────


def test_a_slow_hit_reduces_target_speed_by_10_and_clamps_movement() -> None:
    """(a) A club (slow) hit that deals damage reduces the TARGET's effective
    Speed by 10 ft; its unspent movement budget is clamped to the new cap."""
    club = _LOADER.get_weapon("club")
    assert club is not None
    assert club.mastery == "slow"

    async def _run():
        start, live = await _start(
            "c15-t7-a-slow",
            [_pc("char:hero", "Hero", cell(0, 0))],
            [_mon("mon:foe", "Foe", cell(0, 1))],
        )
        base = _effective_speed(_combatant(live, "mon:foe"), live)
        await submit_player_intent(
            start.handle, actor_id="char:hero", intent=_attack("club", "mon:foe")
        )
        return live, base

    live, base = run_async(_run())
    foe = _combatant(live, "mon:foe")
    assert _effective_speed(foe, live) == base - 10
    assert foe.movement_remaining <= base - 10
    assert live.slow_marks == {"mon:foe": {"char:hero"}}


def test_a_slow_never_stacks_beyond_10_ft() -> None:
    """(a) SRD: "the Speed reduction doesn't exceed 10 feet" — two slow-weapon
    hits from two different attackers still reduce Speed by exactly 10."""

    async def _run():
        start, live = await _start(
            "c15-t7-a-slow-cap",
            [
                _pc("char:hero1", "Hero1", cell(0, 0), initiative=20),
                _pc("char:hero2", "Hero2", cell(1, 0), initiative=15),
            ],
            [_mon("mon:foe", "Foe", cell(0, 1))],
        )
        base = _effective_speed(_combatant(live, "mon:foe"), live)
        await submit_player_intent(
            start.handle, actor_id="char:hero1", intent=_attack("club", "mon:foe")
        )
        await submit_player_intent(
            start.handle, actor_id="char:hero1", intent=_PASS
        )  # club is Light
        await submit_player_intent(
            start.handle, actor_id="char:hero2", intent=_attack("club", "mon:foe")
        )
        return live, base

    live, base = run_async(_run())
    assert live.slow_marks == {"mon:foe": {"char:hero1", "char:hero2"}}
    assert _effective_speed(_combatant(live, "mon:foe"), live) == base - 10


def test_a_slow_expires_at_the_source_attackers_next_turn_start() -> None:
    """(a) "until the start of your next turn" — the SOURCE attacker's own
    next turn. The foe's own intervening turn starts with the reduced
    budget; the hero's next TurnStarted clears the mark."""

    async def _run():
        start, live = await _start(
            "c15-t7-a-slow-expiry",
            [_pc("char:hero", "Hero", cell(0, 0))],
            [_mon("mon:foe", "Foe", cell(0, 1))],
        )
        base = _effective_speed(_combatant(live, "mon:foe"), live)
        await submit_player_intent(
            start.handle, actor_id="char:hero", intent=_attack("club", "mon:foe")
        )
        await submit_player_intent(
            start.handle, actor_id="char:hero", intent=_PASS
        )  # club is Light
        # mon:foe's turn (no template -> auto-pass); its TurnStarted budget
        # reset must project the slowed Speed.
        foe_speed_on_its_turn = _effective_speed(_combatant(live, "mon:foe"), live)
        foe_budget_on_its_turn = _combatant(live, "mon:foe").movement_remaining
        await advance_monster_turn(start.handle)
        # Round wrap -> char:hero's TurnStarted -> mark cleared.
        return live, base, foe_speed_on_its_turn, foe_budget_on_its_turn

    live, base, foe_speed_on_its_turn, foe_budget_on_its_turn = run_async(_run())
    assert foe_speed_on_its_turn == base - 10
    assert foe_budget_on_its_turn == base - 10
    assert live.current_actor_id == "char:hero"
    assert live.slow_marks == {}
    assert _effective_speed(_combatant(live, "mon:foe"), live) == base


def test_a_slow_hit_dealing_zero_damage_does_not_proc() -> None:
    """(a) SRD Slow requires the hit to "deal damage to it" — a bludgeoning-
    immune target takes zero final damage, so no proc is appended."""
    club = _LOADER.get_weapon("club")
    assert club is not None
    activity = next(a for a in club.activities if a.kind == "attack")

    def _procs(*, immune: bool) -> list[tuple[str, str]]:
        ctx = ActivityResolutionContext(
            rng=random.Random(1),
            caster=_hero(),
            targets=[_foe(damage_immunities=["bludgeoning"] if immune else [])],
            event_emitter=lambda _ev: None,
            caster_abilities={"str": 16, "dex": 16, "con": 10, "int": 10, "wis": 10, "cha": 10},
            caster_proficiency_bonus=2,
            caster_level=1,
            variables={"force_d20": 15},
        )
        resolve_activity(activity, ctx, weapon=club)
        return list(ctx.mastery_procs)

    assert _procs(immune=True) == []
    assert _procs(immune=False) == [("slow", "mon:foe")]


# ── (b) Push ─────────────────────────────────────────────────────────────────


def test_b_push_hit_shoves_the_target_10_ft_straight_away() -> None:
    """(b) A greatclub (push) hit moves the target 10 ft directly away from
    the attacker — ``CombatantMoved(forced=True, distance_ft=10)`` and the
    live position update (controller ruling R5: always the full 10 ft)."""
    greatclub = _LOADER.get_weapon("greatclub")
    assert greatclub is not None
    assert greatclub.mastery == "push"

    async def _run():
        start, live = await _start(
            "c15-t7-b-push",
            [_pc("char:hero", "Hero", cell(0, 0))],
            [_mon("mon:foe", "Foe", cell(0, 1))],
        )
        await submit_player_intent(
            start.handle, actor_id="char:hero", intent=_attack("greatclub", "mon:foe")
        )
        return live

    live = run_async(_run())
    moved = [e for e in events_of(live, CombatantMoved) if e.actor_id == "mon:foe"]
    assert len(moved) == 1
    assert moved[0].forced is True
    assert moved[0].distance_ft == 10
    assert moved[0].from_zone == cell(0, 1)
    assert moved[0].to_zone == cell(0, 3)
    assert live.actor_zone["mon:foe"] == cell(0, 3)
    # Push needs only a HIT — no damage-dealt gate, and the proc is a
    # transient fold (no lingering live-state mark).
    assert not hasattr(live, "push_marks")


def test_b_push_against_a_boxed_in_target_is_a_no_op() -> None:
    """(b) A target with nowhere to go (grid edge directly behind it) is
    not moved and no ``CombatantMoved`` fires — ``push_combatant``'s
    primitive no-op."""

    async def _run():
        start, live = await _start(
            "c15-t7-b-push-boxed",
            [_pc("char:hero", "Hero", cell(0, 8))],
            [_mon("mon:foe", "Foe", cell(0, 9))],
        )
        await submit_player_intent(
            start.handle, actor_id="char:hero", intent=_attack("greatclub", "mon:foe")
        )
        return live

    live = run_async(_run())
    assert [e for e in events_of(live, AttackRolled) if e.is_hit]  # the hit landed
    assert events_of(live, CombatantMoved) == []
    assert live.actor_zone["mon:foe"] == cell(0, 9)


# ── (c) Cleave ───────────────────────────────────────────────────────────────


def _cleave_party(**overrides: object) -> list[PartyMemberSpec]:
    return [_pc("char:hero", "Hero", cell(0, 0), **overrides)]


def test_c_cleave_chains_one_extra_attack_into_an_adjacent_second_target() -> None:
    """(c) A greataxe (cleave) hit on mon:a chains ONE extra attack against
    mon:b (within 5 ft of mon:a AND within the hero's 5-ft reach). mon:c is
    within 5 ft of mon:a but 10 ft from the hero (outside reach) — never a
    candidate. The chain's damage is attributed ``mastery:cleave`` and
    carries NO positive STR mod: ``_MaxRandom`` crits every swing, so the
    main hit is 1d12x2 + 3 = 27 and the chain is exactly 24."""
    greataxe = _LOADER.get_weapon("greataxe")
    assert greataxe is not None
    assert greataxe.mastery == "cleave"

    async def _run():
        start, live = await _start(
            "c15-t7-c-cleave",
            _cleave_party(),
            [
                _mon("mon:a", "A", cell(0, 1)),
                _mon("mon:b", "B", cell(1, 1), initiative=9),
                _mon("mon:c", "C", cell(0, 2), initiative=8),
            ],
        )
        await submit_player_intent(
            start.handle, actor_id="char:hero", intent=_attack("greataxe", "mon:a")
        )
        return live

    live = run_async(_run())
    swings = [e for e in events_of(live, AttackRolled) if e.attacker_id == "char:hero"]
    assert [s.target_id for s in swings] == ["mon:a", "mon:b"]
    assert all(s.is_hit for s in swings)
    # Full to-hit on the chain: same modifier as the main swing.
    assert swings[1].modifier == swings[0].modifier
    damage = {e.target_id: e for e in events_of(live, DamageApplied)}
    assert damage["mon:a"].source_id == "greataxe"
    assert damage["mon:a"].amount == 27
    assert damage["mon:b"].source_id == "mastery:cleave"
    assert damage["mon:b"].amount == 24
    assert _combatant(live, "char:hero").cleave_spent_this_turn is True


def test_c_cleave_fires_only_once_per_turn() -> None:
    """(c) "You can make this extra attack only once per turn" — a level-5
    Fighter (Extra Attack) swings the greataxe twice at mon:a; only the
    FIRST hit chains (3 hero AttackRolled, not 4), and the cap resets at
    the hero's next turn start."""

    async def _run():
        start, live = await _start(
            "c15-t7-c-cleave-once",
            _cleave_party(class_slug="fighter", character_level=5),
            [_mon("mon:a", "A", cell(0, 1)), _mon("mon:b", "B", cell(1, 1), initiative=9)],
        )
        await submit_player_intent(
            start.handle, actor_id="char:hero", intent=_attack("greataxe", "mon:a")
        )
        await submit_player_intent(
            start.handle, actor_id="char:hero", intent=_attack("greataxe", "mon:a")
        )
        spent_mid_turn = _combatant(live, "char:hero").cleave_spent_this_turn
        # An Extra-Attack actor keeps the turn until it passes (C14 R1).
        await submit_player_intent(start.handle, actor_id="char:hero", intent=_PASS)
        await advance_monster_turn(start.handle)  # mon:a
        await advance_monster_turn(start.handle)  # mon:b -> round wrap -> hero
        return live, spent_mid_turn

    live, spent_mid_turn = run_async(_run())
    swings = [e for e in events_of(live, AttackRolled) if e.attacker_id == "char:hero"]
    assert [s.target_id for s in swings] == ["mon:a", "mon:b", "mon:a"]
    assert spent_mid_turn is True
    assert live.current_actor_id == "char:hero"
    assert _combatant(live, "char:hero").cleave_spent_this_turn is False


def test_c_cleave_without_a_candidate_does_not_chain() -> None:
    """(c) No living hostile within 5 ft of the first target and within reach
    -> no chain, no extra draw, cap NOT spent."""

    async def _run():
        start, live = await _start(
            "c15-t7-c-cleave-none",
            _cleave_party(),
            [_mon("mon:a", "A", cell(0, 1)), _mon("mon:far", "Far", cell(5, 5), initiative=9)],
        )
        await submit_player_intent(
            start.handle, actor_id="char:hero", intent=_attack("greataxe", "mon:a")
        )
        return live

    live = run_async(_run())
    swings = [e for e in events_of(live, AttackRolled) if e.attacker_id == "char:hero"]
    assert [s.target_id for s in swings] == ["mon:a"]
    assert _combatant(live, "char:hero").cleave_spent_this_turn is False


def test_c_cleave_chain_hit_does_not_re_proc_cleave() -> None:
    """(c) The chained hit never itself chains: mon:b (picked by the
    ascending-entity_id tie-break over mon:d, both 5 ft from the hero and
    from mon:a) is hit, and mon:d — adjacent to mon:b and within reach — is
    NOT attacked. Exactly two hero swings."""

    async def _run():
        start, live = await _start(
            "c15-t7-c-cleave-no-recursion",
            _cleave_party(),
            [
                _mon("mon:a", "A", cell(0, 1)),
                _mon("mon:b", "B", cell(1, 1), initiative=9),
                _mon("mon:d", "D", cell(1, 0), initiative=8),
            ],
        )
        await submit_player_intent(
            start.handle, actor_id="char:hero", intent=_attack("greataxe", "mon:a")
        )
        return live

    live = run_async(_run())
    swings = [e for e in events_of(live, AttackRolled) if e.attacker_id == "char:hero"]
    assert [s.target_id for s in swings] == ["mon:a", "mon:b"]
    assert {e.target_id for e in events_of(live, DamageApplied)} == {"mon:a", "mon:b"}


# ── (d) Nick ─────────────────────────────────────────────────────────────────


def test_d_nick_offhand_swing_keeps_the_bonus_action() -> None:
    """(d) Dagger main-hand (Light) then scimitar off-hand (Nick, Light): the
    off-hand swing resolves as part of the Attack action — the Bonus Action
    is STILL available afterwards, the once-per-turn ``offhand_attack_spent``
    cap is set, and the Light-property mod suppression still applies
    (scimitar 1d6 crit under ``_MaxRandom`` = 12, no +3)."""
    scimitar = _LOADER.get_weapon("scimitar")
    assert scimitar is not None
    assert scimitar.mastery == "nick"

    async def _run():
        start, live = await _start(
            "c15-t7-d-nick",
            [_pc("char:hero", "Hero", cell(0, 0))],
            [_mon("mon:foe", "Foe", cell(0, 1))],
        )
        await submit_player_intent(
            start.handle, actor_id="char:hero", intent=_attack("dagger", "mon:foe")
        )
        await submit_player_intent(
            start.handle, actor_id="char:hero", intent=_attack("scimitar", "mon:foe")
        )
        return live

    live = run_async(_run())
    hero = _combatant(live, "char:hero")
    assert hero.offhand_attack_spent is True
    assert hero.bonus_action_available is True
    assert live.current_actor_id == "char:hero"  # the turn stays open
    damage = events_of(live, DamageApplied)
    assert [e.source_id for e in damage] == ["dagger", "scimitar"]
    assert damage[-1].amount == 12


def test_d_non_nick_offhand_swing_still_spends_the_bonus_action() -> None:
    """(d)-control: dagger main-hand then shortsword (vex, Light) off-hand —
    the ordinary Two-Weapon Fighting economy: Bonus Action spent."""

    async def _run():
        start, live = await _start(
            "c15-t7-d-non-nick",
            [_pc("char:hero", "Hero", cell(0, 0))],
            [_mon("mon:foe", "Foe", cell(0, 1))],
        )
        await submit_player_intent(
            start.handle, actor_id="char:hero", intent=_attack("dagger", "mon:foe")
        )
        await submit_player_intent(
            start.handle, actor_id="char:hero", intent=_attack("shortsword", "mon:foe")
        )
        return live

    live = run_async(_run())
    hero = _combatant(live, "char:hero")
    assert hero.offhand_attack_spent is True
    assert hero.bonus_action_available is False


def _spend_bonus_action(live, entity_id: str) -> None:
    for idx, c in enumerate(live.initiative):
        if c.entity_id == entity_id:
            live.initiative[idx] = c.model_copy(update={"bonus_action_available": False})
            break


def test_d_nick_offhand_swing_resolves_even_with_the_bonus_action_already_spent() -> None:
    """(d) Nick fidelity (controller ruling): "as part of the Attack action
    instead of as a Bonus Action" — a Nick off-hand swing needs NO Bonus
    Action. With the hero's Bonus Action already spent, dagger main-hand ->
    scimitar (Nick) off-hand RESOLVES; the same state with a non-Nick
    off-hand (handaxe, vex) is rejected exactly as before (``AttackFailed
    (no_action_economy)``, turn kept)."""

    async def _run(offhand: str):
        start, live = await _start(
            f"c15-t7-d-nick-no-ba-{offhand}",
            [_pc("char:hero", "Hero", cell(0, 0))],
            [_mon("mon:foe", "Foe", cell(0, 1))],
        )
        _spend_bonus_action(live, "char:hero")
        await submit_player_intent(
            start.handle, actor_id="char:hero", intent=_attack("dagger", "mon:foe")
        )
        await submit_player_intent(
            start.handle, actor_id="char:hero", intent=_attack(offhand, "mon:foe")
        )
        return live

    nick = run_async(_run("scimitar"))
    assert [e.source_id for e in events_of(nick, DamageApplied)] == ["dagger", "scimitar"]
    hero = _combatant(nick, "char:hero")
    assert hero.offhand_attack_spent is True
    assert hero.bonus_action_available is False

    plain = run_async(_run("handaxe"))
    assert [e.source_id for e in events_of(plain, DamageApplied)] == ["dagger"]
    failures = [e for e in events_of(plain, AttackFailed) if e.actor_id == "char:hero"]
    assert failures
    assert failures[-1].reason == "no_action_economy"
    assert _combatant(plain, "char:hero").offhand_attack_spent is False


# ── (c) Cleave — fix round 1: full per-target geometry on the chained roll ──


class _FixedRandom(random.Random):
    """Every ``randint`` draw returns a fixed pip count (attack d20 AND damage
    dice) so a hit/miss boundary is exact."""

    def __init__(self, pips: int) -> None:
        super().__init__(0)
        self._pips = pips

    def randint(self, a: int, b: int) -> int:
        return min(max(self._pips, a), b)


def _set_dodging(live, entity_id: str) -> None:
    for idx, c in enumerate(live.initiative):
        if c.entity_id == entity_id:
            live.initiative[idx] = c.model_copy(update={"dodging": True})
            break


def test_c_cleave_chain_honors_a_dodging_candidate() -> None:
    """Fix round 1 — the chained roll gets the candidate's OWN per-target
    geometry: a Dodging mon:b imposes Disadvantage (``"dodge"`` source) on
    the chained ``AttackRolled`` exactly as it would on a main swing."""

    async def _run():
        start, live = await _start(
            "c15-t7-c-cleave-dodge",
            _cleave_party(),
            [_mon("mon:a", "A", cell(0, 1)), _mon("mon:b", "B", cell(1, 1), initiative=9)],
        )
        _set_dodging(live, "mon:b")
        await submit_player_intent(
            start.handle, actor_id="char:hero", intent=_attack("greataxe", "mon:a")
        )
        return live

    live = run_async(_run())
    swings = [e for e in events_of(live, AttackRolled) if e.attacker_id == "char:hero"]
    assert [s.target_id for s in swings] == ["mon:a", "mon:b"]
    assert "dodge" not in swings[0].sources
    assert "dodge" in swings[1].sources
    assert swings[1].advantage == "disadvantage"


def test_c_cleave_chain_honors_three_quarters_cover_on_the_candidate() -> None:
    """Fix round 1 — cover geometry on the chained roll: with a fixed d20 of
    10 the hero's total is 10 + 3 (STR) + 2 (prof) = 15 vs mon:b AC 14 — a
    HIT in the open, a MISS behind three-quarters cover (+5 -> effective
    AC 19). Control and covered runs differ ONLY in ``cover_cells``."""

    async def _run(*, covered: bool):
        start = await start_combat(
            session_id=f"c15-t7-c-cleave-cover-{covered}",
            party=_cleave_party(),
            encounter=[
                _mon("mon:a", "A", cell(0, 1)),
                _mon("mon:b", "B", cell(1, 1), initiative=9, ac=14),
            ],
            scene_zones=None,
            grid_scene=grid_scene(cover_cells={cell(1, 1): "three_quarters"} if covered else {}),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        live.rng = _FixedRandom(10)
        await submit_player_intent(
            start.handle, actor_id="char:hero", intent=_attack("greataxe", "mon:a")
        )
        return live

    def _chain(live):
        swings = [e for e in events_of(live, AttackRolled) if e.attacker_id == "char:hero"]
        assert [s.target_id for s in swings] == ["mon:a", "mon:b"]
        assert swings[1].roll_total == 15
        return swings[1]

    assert _chain(run_async(_run(covered=False))).is_hit is True
    assert _chain(run_async(_run(covered=True))).is_hit is False
