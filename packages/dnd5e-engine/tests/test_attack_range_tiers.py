"""C15 Task 2 — long-range disadvantage tiers and Thrown attacks
(closes C15-S03).

SRD 5.2 §Range (packs/_source/content24/appendices/appendix-d-rule-
references.yml, id HjKXuB8ndjcqOds7): "Your attack roll has Disadvantage
when your target is beyond normal range, and you can't attack a target
beyond long range." Three tiers: ``distance <= normal`` (plain),
``normal < distance <= long`` (Disadvantage — a LEGAL attack), ``distance
> long`` (illegal, ``AttackFailed(reason="out_of_range")``).

SRD 5.2 §Thrown: "If a weapon has the Thrown property, you can throw the
weapon to make a ranged attack... If the weapon is a Melee weapon, use the
same ability modifier for the attack and damage rolls that you use for a
melee attack with that weapon."

light-crossbow: melee reach n/a, ``range.value=80``, ``range.long=320``.
dagger: melee, ``thrown`` property, ``range.value=20``, ``range.long=60``.
longsword: melee, no ``thrown``, no numeric range (reach 5ft only).

Grid cells are 5ft each (``cell(col, 0)`` at column ``col`` sits
``col * 5`` ft from ``cell(0, 0)`` — see ``tests/e2e/test_c15_attack_rules.py``
S03, which uses the same convention).
"""

from __future__ import annotations

from dnd5e_engine import PlayerIntent
from dnd5e_engine.events import AttackFailed, AttackRolled
from dnd5e_engine.lib_loader import get_lib_loader
from dnd5e_engine.orchestrator import (
    _get_live,
    _weapon_attack_range_ft,
    start_combat,
    submit_player_intent,
)
from dnd5e_engine.specs import EncounterMemberSpec, GridScene, PartyMemberSpec
from tests.e2e.harness import cell, events_of, run_async

LIGHT_CROSSBOW = get_lib_loader().get_weapon("light-crossbow")
DAGGER = get_lib_loader().get_weapon("dagger")
LONGSWORD = get_lib_loader().get_weapon("longsword")


# ── Unit tests: `_weapon_attack_range_ft` band derivation ───────────────


def test_ranged_weapon_bands_are_value_and_long():
    assert _weapon_attack_range_ft(LIGHT_CROSSBOW) == (80, 320)


def test_melee_non_thrown_weapon_bands_are_reach_reach():
    assert _weapon_attack_range_ft(LONGSWORD) == (5, 5)


def test_melee_thrown_weapon_bands_are_value_and_long():
    # normal = max(reach=5, value=20) = 20; max = long = 60.
    assert _weapon_attack_range_ft(DAGGER) == (20, 60)


# ── End-to-end: PC attacks at increasing distance ────────────────────────


def _hero(**overrides: object) -> PartyMemberSpec:
    kwargs: dict = dict(
        entity_id="char:hero",
        name="Hero",
        initiative=20,
        hp_current=20,
        hp_max=20,
        strength=16,
        dexterity=14,
        zone_id=cell(0, 0),
    )
    kwargs.update(overrides)
    return PartyMemberSpec(**kwargs)


def _foe(col: int) -> EncounterMemberSpec:
    return EncounterMemberSpec(
        entity_id="mon:foe",
        entity_type="Monster",
        name="Foe",
        initiative=1,
        hp_current=100,
        hp_max=100,
        ac=15,
        zone_id=cell(col, 0),
    )


def _attack_at(weapon_id: str, col: int, session_id: str, *, hero: PartyMemberSpec | None = None):
    async def _inner():
        start = await start_combat(
            session_id=session_id,
            party=[hero or _hero()],
            encounter=[_foe(col)],
            scene_zones=None,
            grid_scene=GridScene(width=200, height=10),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="attack", weapon_id=weapon_id, target_id="mon:foe"),
        )
        return live

    return run_async(_inner())


# Light crossbow (ranged, 80/320) — normal / disadvantage / reject.


def test_light_crossbow_at_50ft_rolls_normal():
    live = _attack_at("light-crossbow", 10, "c15-t2-crossbow-normal")
    rolled = events_of(live, AttackRolled)
    assert rolled
    assert rolled[0].advantage == "normal"


def test_light_crossbow_at_200ft_rolls_disadvantage_with_range_long_source():
    live = _attack_at("light-crossbow", 40, "c15-t2-crossbow-middle")
    rolled = events_of(live, AttackRolled)
    assert rolled, "expected a legal (disadvantaged) attack roll at 200 ft"
    assert rolled[0].advantage == "disadvantage"
    assert "range:long" in rolled[0].sources


def test_light_crossbow_at_500ft_is_rejected_out_of_range():
    live = _attack_at("light-crossbow", 100, "c15-t2-crossbow-reject")
    failed = events_of(live, AttackFailed)
    assert failed
    assert failed[0].reason == "out_of_range"


# Dagger (melee + thrown, 20/60) — melee swing / normal throw / disadvantage / reject.


def test_dagger_at_5ft_is_a_melee_swing():
    live = _attack_at("dagger", 1, "c15-t2-dagger-melee")
    rolled = events_of(live, AttackRolled)
    assert rolled
    assert rolled[0].advantage == "normal"


def test_dagger_at_20ft_resolves_as_a_normal_thrown_attack():
    # Previously rejected (old gate keyed off ``range.value`` as the ONLY
    # band, but the reach-derived "melee reach" path never surfaced the
    # thrown value at all) — now legal, no disadvantage.
    live = _attack_at("dagger", 4, "c15-t2-dagger-thrown-normal")
    rolled = events_of(live, AttackRolled)
    assert rolled, "expected a legal, un-penalized thrown attack at 20 ft"
    assert rolled[0].advantage == "normal"


def test_dagger_at_40ft_rolls_disadvantage():
    live = _attack_at("dagger", 8, "c15-t2-dagger-thrown-dis")
    rolled = events_of(live, AttackRolled)
    assert rolled, "expected a legal (disadvantaged) thrown attack at 40 ft"
    assert rolled[0].advantage == "disadvantage"
    assert "range:long" in rolled[0].sources


def test_dagger_at_100ft_is_rejected_out_of_range():
    live = _attack_at("dagger", 20, "c15-t2-dagger-thrown-reject")
    failed = events_of(live, AttackFailed)
    assert failed
    assert failed[0].reason == "out_of_range"


def test_dagger_thrown_at_range_uses_same_ability_modifier_as_melee_swing():
    """SRD §Thrown: "use the same ability modifier for the attack and
    damage rolls that you use for a melee attack with that weapon." Same
    rng seed + same weapon + no other divergence between the two calls
    (the only variable is distance) ⇒ an identical natural die AND an
    identical attack bonus give an identical roll_total. A modifier switch
    (e.g. accidentally forcing DEX for a "ranged" thrown swing) would
    change ``roll_total`` since STR (16, +3) != DEX (14, +2) here.
    """
    live_melee = _attack_at("dagger", 1, "c15-t2-dagger-ability-melee")
    live_thrown = _attack_at("dagger", 4, "c15-t2-dagger-ability-thrown")
    melee_rolled = events_of(live_melee, AttackRolled)
    thrown_rolled = events_of(live_thrown, AttackRolled)
    assert melee_rolled
    assert thrown_rolled
    assert melee_rolled[0].advantage == thrown_rolled[0].advantage == "normal"
    assert melee_rolled[0].natural == thrown_rolled[0].natural
    assert melee_rolled[0].roll_total == thrown_rolled[0].roll_total


# Longsword (melee, no thrown) — no disadvantage tier; still rejected beyond reach.


def test_longsword_at_10ft_is_still_rejected():
    live = _attack_at("longsword", 2, "c15-t2-longsword-reject")
    failed = events_of(live, AttackFailed)
    assert failed
    assert failed[0].reason == "out_of_range"
