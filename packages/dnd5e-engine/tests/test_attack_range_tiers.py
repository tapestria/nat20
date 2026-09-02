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

from dnd5e_engine import ActiveEffect, PlayerIntent
from dnd5e_engine.events import AttackFailed, AttackRolled
from dnd5e_engine.lib_loader import get_lib_loader
from dnd5e_engine.orchestrator import (
    _get_live,
    _hostile_adjacent_to_attacker,
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


# ── C15 Task 3 — Ranged-in-melee + Heavy property (closes C15-S02) ──────
#
# SRD 5.2 "Ranged Attacks in Close Combat" (packs/_source/content24/
# appendices/appendix-d-rule-references.yml, id qEZvxW0NM7ixSQP5): "you
# have Disadvantage on the roll if you are within 5 feet of an enemy who
# can see you and doesn't have the Incapacitated condition."
#
# SRD 5.2 Heavy: "You have Disadvantage on attack rolls with a Heavy
# weapon if it's a Melee weapon and your Strength score isn't at least 13
# or if it's a Ranged weapon and your Dexterity score isn't at least 13."
# (2024 rule — not the 2014 Small-creature rule.)
#
# longbow: martial_ranged, Heavy, 150/600ft. greatsword: martial_melee,
# Heavy, reach 5ft only. heavy-crossbow: martial_ranged, Heavy, 100/400ft.

LONGBOW = get_lib_loader().get_weapon("longbow")
GREATSWORD = get_lib_loader().get_weapon("greatsword")
HEAVY_CROSSBOW = get_lib_loader().get_weapon("heavy-crossbow")


def _named_foe(entity_id: str, col: int, *, initiative: int = 1) -> EncounterMemberSpec:
    return EncounterMemberSpec(
        entity_id=entity_id,
        entity_type="Monster",
        name=entity_id,
        initiative=initiative,
        hp_current=100,
        hp_max=100,
        ac=15,
        zone_id=cell(col, 0),
    )


def _weapon_attack(
    weapon_id: str,
    session_id: str,
    *,
    encounter: list[EncounterMemberSpec],
    target_id: str,
    hero: PartyMemberSpec | None = None,
    active_effects: tuple = (),
    grid_scene: GridScene | None = None,
):
    async def _inner():
        start = await start_combat(
            session_id=session_id,
            party=[hero or _hero()],
            encounter=encounter,
            scene_zones=None,
            grid_scene=grid_scene or GridScene(width=200, height=10),
            active_effects=list(active_effects),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="attack", weapon_id=weapon_id, target_id=target_id),
        )
        return live

    return run_async(_inner())


# (a) Ranged attack, living adjacent hostile who is not the target → disadvantage.


def test_longbow_disadvantaged_by_a_living_adjacent_hostile_not_the_target():
    near = _named_foe("mon:near", 1, initiative=2)  # 5 ft from hero
    far = _named_foe("mon:far", 10, initiative=1)  # 50 ft from hero
    live = _weapon_attack(
        "longbow", "c15-t3-ranged-in-melee", encounter=[far, near], target_id="mon:far"
    )
    rolled = next(e for e in events_of(live, AttackRolled) if e.target_id == "mon:far")
    assert rolled.advantage == "disadvantage"
    assert "ranged_in_melee" in rolled.sources


# (b) No adjacent hostile → normal.


def test_longbow_normal_with_no_adjacent_hostile():
    far = _named_foe("mon:far", 10, initiative=1)
    live = _weapon_attack("longbow", "c15-t3-no-adjacent", encounter=[far], target_id="mon:far")
    rolled = next(e for e in events_of(live, AttackRolled) if e.target_id == "mon:far")
    assert rolled.advantage == "normal"
    assert "ranged_in_melee" not in rolled.sources


# (c) Adjacent hostile Incapacitated (Stunned) → the SRD conjunct excludes it.


def test_longbow_normal_when_adjacent_hostile_is_stunned():
    near = _named_foe("mon:near", 1, initiative=2)
    far = _named_foe("mon:far", 10, initiative=1)
    stunned = ActiveEffect(
        id="effect:stunned:mon:near",
        name="Stunned",
        origin="test:cond",
        target_id="mon:near",
        statuses={"stunned"},
    )
    live = _weapon_attack(
        "longbow",
        "c15-t3-stunned-adjacent",
        encounter=[far, near],
        target_id="mon:far",
        active_effects=(stunned,),
    )
    rolled = next(e for e in events_of(live, AttackRolled) if e.target_id == "mon:far")
    assert rolled.advantage == "normal"
    assert "ranged_in_melee" not in rolled.sources


# (d) Adjacent hostile that cannot see the attacker — direct unit test of the
# helper (a full e2e wiring would also make the ranged TARGET unable to see
# the attacker via the same darkness, adding an unrelated "unseen" advantage
# source that would mask the assertion; see task-3-report.md).


def test_hostile_adjacent_helper_excludes_a_hostile_that_cannot_see_the_attacker():
    near = _named_foe("mon:near", 1, initiative=2)  # 5 ft away, no darkvision

    async def _inner():
        start = await start_combat(
            session_id="c15-t3-blind-adjacent",
            party=[_hero()],
            encounter=[near],
            scene_zones=None,
            # Darkness on the ATTACKER's own cell — the adjacent monster has
            # no darkvision by default (EncounterMemberSpec carries no
            # ``senses`` override), so it cannot see into it.
            grid_scene=GridScene(width=200, height=10, lighting={cell(0, 0): "dark"}),
            rng_seed=1,
        )
        return _get_live(start.handle)

    live = run_async(_inner())
    hero_combatant = next(c for c in live.initiative if c.entity_id == "char:hero")
    assert _hostile_adjacent_to_attacker(live, hero_combatant) is False


def test_hostile_adjacent_helper_true_for_a_seeing_adjacent_hostile():
    near = _named_foe("mon:near", 1, initiative=2)

    async def _inner():
        start = await start_combat(
            session_id="c15-t3-seeing-adjacent",
            party=[_hero()],
            encounter=[near],
            scene_zones=None,
            grid_scene=GridScene(width=200, height=10),
            rng_seed=1,
        )
        return _get_live(start.handle)

    live = run_async(_inner())
    hero_combatant = next(c for c in live.initiative if c.entity_id == "char:hero")
    assert _hostile_adjacent_to_attacker(live, hero_combatant) is True


# (e) MELEE attack — never penalized, even with a (necessarily adjacent) hostile.


def test_melee_attack_is_unaffected_by_an_adjacent_hostile():
    near = _named_foe("mon:near", 1, initiative=2)  # the melee target itself, 5 ft away
    live = _weapon_attack(
        "longsword", "c15-t3-melee-unaffected", encounter=[near], target_id="mon:near"
    )
    rolled = next(e for e in events_of(live, AttackRolled) if e.target_id == "mon:near")
    assert rolled.advantage == "normal"
    assert "ranged_in_melee" not in rolled.sources


# (f) Heavy — melee (STR-gated) and ranged (DEX-gated).


def test_heavy_melee_weapon_disadvantaged_below_str_13():
    far = _named_foe("mon:near", 1, initiative=1)  # greatsword reach is 5ft only
    live = _weapon_attack(
        "greatsword",
        "c15-t3-heavy-melee-low-str",
        encounter=[far],
        target_id="mon:near",
        hero=_hero(strength=11),
    )
    rolled = next(e for e in events_of(live, AttackRolled) if e.target_id == "mon:near")
    assert rolled.advantage == "disadvantage"
    assert "trait" in rolled.sources


def test_heavy_melee_weapon_normal_at_str_13():
    far = _named_foe("mon:near", 1, initiative=1)
    live = _weapon_attack(
        "greatsword",
        "c15-t3-heavy-melee-ok-str",
        encounter=[far],
        target_id="mon:near",
        hero=_hero(strength=13),
    )
    rolled = next(e for e in events_of(live, AttackRolled) if e.target_id == "mon:near")
    assert rolled.advantage == "normal"
    assert "trait" not in rolled.sources


def test_heavy_ranged_weapon_disadvantaged_below_dex_13():
    far = _named_foe("mon:far", 10, initiative=1)
    live = _weapon_attack(
        "heavy-crossbow",
        "c15-t3-heavy-ranged-low-dex",
        encounter=[far],
        target_id="mon:far",
        hero=_hero(dexterity=11),
    )
    rolled = next(e for e in events_of(live, AttackRolled) if e.target_id == "mon:far")
    assert rolled.advantage == "disadvantage"
    assert "trait" in rolled.sources


def test_heavy_ranged_weapon_normal_at_dex_13():
    far = _named_foe("mon:far", 10, initiative=1)
    live = _weapon_attack(
        "heavy-crossbow",
        "c15-t3-heavy-ranged-ok-dex",
        encounter=[far],
        target_id="mon:far",
        hero=_hero(dexterity=13),
    )
    rolled = next(e for e in events_of(live, AttackRolled) if e.target_id == "mon:far")
    assert rolled.advantage == "normal"
    assert "trait" not in rolled.sources
