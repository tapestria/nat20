"""C15 Task 1 — the real weapon-proficiency gate (closes C15-S01).

SRD 5.2 (packs/_source/content24/chapter-6/equipment.yml, id
dWQ2ZTLOuKr3PMAx, heading "Weapon Proficiency"): "Anyone can wield a
weapon, but you must have proficiency with it to add your Proficiency
Bonus to an attack roll you make with it." Proficiency Bonus is OMITTED
when unproficient, never subtracted.

R1 (binding controller ruling) — ``PartyMemberSpec.weapon_proficiencies``
defaults to ``()``, which is ALSO the legitimate "proficient in nothing"
declaration. The two are made distinguishable by widening
``Combatant.weapon_proficiencies`` to ``list[str] | None``: ``None`` (the
host never set the spec field) means "assume proficient" (legacy
behaviour, byte-identical to every pre-C15 fixture); an explicit list
(possibly empty) means "enforce — proficient iff the weapon's
``weapon_category`` or ``slug`` is listed". Monsters never carry this
field explicitly, so their Combatant's ``weapon_proficiencies`` stays
``None`` -> always proficient, matching the SRD "a monster is proficient
with any weapon in its stat block" rule.
"""

from __future__ import annotations

from dnd5e_engine import PlayerIntent
from dnd5e_engine.events import AttackRolled
from dnd5e_engine.lib_loader import get_lib_loader
from dnd5e_engine.orchestrator import (
    _get_live,
    _is_proficient_with_weapon,
    advance_monster_turn,
    start_combat,
    submit_player_intent,
)
from dnd5e_engine.specs import EncounterMemberSpec, PartyMemberSpec
from dnd5e_engine.types.combat import Combatant
from tests.e2e.harness import cell, events_of, grid_scene, run_async

LONGSWORD = get_lib_loader().get_weapon("longsword")


def _hero(**overrides: object) -> Combatant:
    base = dict(
        entity_id="char:hero",
        entity_type="Character",
        name="Hero",
        initiative=20,
        hp_current=20,
        character_level=1,
    )
    base.update(overrides)
    return Combatant(**base)


# ── Unit tests: `_is_proficient_with_weapon` helper ─────────────────────


def test_helper_sentinel_none_means_proficient_with_anything():
    combatant = _hero(weapon_proficiencies=None)
    assert _is_proficient_with_weapon(combatant, LONGSWORD) is True


def test_helper_weapon_none_means_proficient():
    combatant = _hero(weapon_proficiencies=[])
    assert _is_proficient_with_weapon(combatant, None) is True


def test_helper_explicit_empty_list_means_not_proficient_with_a_weapon():
    combatant = _hero(weapon_proficiencies=[])
    assert _is_proficient_with_weapon(combatant, LONGSWORD) is False


def test_helper_category_match_means_proficient():
    combatant = _hero(weapon_proficiencies=["martial_melee"])
    assert _is_proficient_with_weapon(combatant, LONGSWORD) is True


def test_helper_slug_match_means_proficient():
    combatant = _hero(weapon_proficiencies=["longsword"])
    assert _is_proficient_with_weapon(combatant, LONGSWORD) is True


def test_helper_wrong_category_means_not_proficient():
    combatant = _hero(weapon_proficiencies=["simple_melee"])
    assert _is_proficient_with_weapon(combatant, LONGSWORD) is False


# ── R1 sentinel threading: PartyMemberSpec -> Combatant ─────────────────


def _party_of_one(**hero_kwargs: object) -> list[PartyMemberSpec]:
    kwargs: dict = dict(
        entity_id="char:hero",
        name="Hero",
        initiative=20,
        hp_current=20,
        hp_max=20,
        strength=16,
        character_level=1,
        zone_id=cell(0, 0),
    )
    kwargs.update(hero_kwargs)
    return [PartyMemberSpec(**kwargs)]


def _foe() -> EncounterMemberSpec:
    return EncounterMemberSpec(
        entity_id="mon:foe",
        entity_type="Monster",
        name="Foe",
        initiative=1,
        hp_current=500,
        hp_max=500,
        ac=1,
        zone_id=cell(0, 1),
    )


def _start_and_attack(party: list[PartyMemberSpec], session_id: str):
    async def _inner():
        start = await start_combat(
            session_id=session_id,
            party=party,
            encounter=[_foe()],
            scene_zones=None,
            grid_scene=grid_scene(),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="attack", weapon_id="longsword", target_id="mon:foe"),
        )
        return live

    return run_async(_inner())


def test_r1_sentinel_field_not_set_yields_none_on_combatant():
    live = _start_and_attack(_party_of_one(), "c15-t1-r1-unset")
    hero = next(c for c in live.initiative if c.entity_id == "char:hero")
    assert hero.weapon_proficiencies is None


def test_r1_sentinel_explicit_empty_tuple_yields_empty_list_on_combatant():
    live = _start_and_attack(_party_of_one(weapon_proficiencies=()), "c15-t1-r1-empty")
    hero = next(c for c in live.initiative if c.entity_id == "char:hero")
    assert hero.weapon_proficiencies == []


def test_r1_sentinel_explicit_list_threads_through():
    live = _start_and_attack(
        _party_of_one(weapon_proficiencies=("martial_melee",)), "c15-t1-r1-list"
    )
    hero = next(c for c in live.initiative if c.entity_id == "char:hero")
    assert hero.weapon_proficiencies == ["martial_melee"]


# ── End-to-end: attack totals reflect the proficiency gate ──────────────


def _attack_total(party: list[PartyMemberSpec], session_id: str) -> int:
    async def _inner():
        start = await start_combat(
            session_id=session_id,
            party=party,
            encounter=[_foe()],
            scene_zones=None,
            grid_scene=grid_scene(),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="attack", weapon_id="longsword", target_id="mon:foe"),
        )
        return live

    live = run_async(_inner())
    return next(e for e in events_of(live, AttackRolled) if e.target_id == "mon:foe").roll_total


def test_field_not_set_pins_the_legacy_always_proficient_total():
    # The R1 sentinel (weapon_proficiencies unset -> None -> always
    # proficient) makes an unset-field attacker's total identical to an
    # attacker explicitly proficient with the weapon's own category.
    base_total = _attack_total(_party_of_one(), "c15-t1-legacy-pin")
    explicit_martial = _attack_total(
        _party_of_one(weapon_proficiencies=("martial_melee",)), "c15-t1-legacy-pin-cmp"
    )
    assert base_total == explicit_martial


def test_explicit_empty_tuple_omits_proficiency_bonus():
    base_total = _attack_total(_party_of_one(), "c15-t1-diff-base")
    nonprof_total = _attack_total(_party_of_one(weapon_proficiencies=()), "c15-t1-diff-nonprof")
    # Proficiency Bonus at level 1 is +2, omitted entirely (never a penalty).
    assert base_total - nonprof_total == 2


def test_explicit_category_match_stays_proficient():
    base_total = _attack_total(_party_of_one(), "c15-t1-cat-base")
    prof_total = _attack_total(
        _party_of_one(weapon_proficiencies=("martial_melee",)), "c15-t1-cat-prof"
    )
    assert base_total == prof_total


def test_explicit_slug_match_stays_proficient():
    base_total = _attack_total(_party_of_one(), "c15-t1-slug-base")
    prof_total = _attack_total(
        _party_of_one(weapon_proficiencies=("longsword",)), "c15-t1-slug-prof"
    )
    assert base_total == prof_total


def test_explicit_wrong_category_is_not_proficient():
    base_total = _attack_total(_party_of_one(), "c15-t1-wrong-base")
    nonprof_total = _attack_total(
        _party_of_one(weapon_proficiencies=("simple_melee",)), "c15-t1-wrong-nonprof"
    )
    assert base_total - nonprof_total == 2


# ── Monsters stay always-proficient (SRD stat-block rule) ───────────────


def test_monster_combatant_weapon_proficiencies_stays_none():
    async def _inner():
        start = await start_combat(
            session_id="c15-t1-monster-pin",
            party=_party_of_one(),
            encounter=[_foe()],
            scene_zones=None,
            grid_scene=grid_scene(),
            rng_seed=1,
        )
        return _get_live(start.handle)

    live = run_async(_inner())
    foe = next(c for c in live.initiative if c.entity_id == "mon:foe")
    assert foe.weapon_proficiencies is None


def test_monster_attack_unaffected_by_proficiency_gate():
    async def _inner():
        start = await start_combat(
            session_id="c15-t1-monster-attack",
            party=[
                PartyMemberSpec(
                    entity_id="char:hero",
                    name="Hero",
                    initiative=1,
                    hp_current=20,
                    hp_max=20,
                    ac=1,
                    zone_id=cell(0, 0),
                )
            ],
            encounter=[
                EncounterMemberSpec(
                    entity_id="mon:foe",
                    entity_type="Monster",
                    name="Foe",
                    initiative=20,
                    hp_current=50,
                    hp_max=50,
                    ac=15,
                    zone_id=cell(0, 1),
                )
            ],
            scene_zones=None,
            grid_scene=grid_scene(),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        await advance_monster_turn(start.handle)
        return live

    live = run_async(_inner())
    rolled = [e for e in events_of(live, AttackRolled) if e.attacker_id == "mon:foe"]
    assert rolled, "expected the monster to attack on its turn"


# ── Adjacent fix: Combatant.attack_bonus sentinel ────────────────────────
#
# Discovered while TDD-ing this task: ``build_activity_context`` always
# forwarded ``caster.attack_bonus`` into ``ActivityResolutionContext
# .attack_bonus_override``, and ``activities/attack.py::_attack_bonus``
# returns that override VERBATIM whenever it is not ``None`` — including
# ``0``, the pre-C15 ``Combatant.attack_bonus`` default. That meant a bare
# ``PartyMemberSpec`` (no ``attack_bonus=`` set — exactly C15-S01's setup)
# always resolved a 0 to-hit modifier, silently swallowing BOTH the
# governing-ability mod AND the proficiency bonus, so the proficiency gate
# had nothing to gate: proficient and non-proficient totals were always
# identical (5 == 5, not 5 == 3). Fixed the same way as the R1 sentinel:
# ``Combatant.attack_bonus`` widened to ``int | None``, threaded ``None``
# from ``PartyMemberSpec`` via the same ``model_fields_set`` check, and every
# direct arithmetic reader (``_caster_mod`` / ``_save_dc`` / the two
# opportunity-attack fire sites) guards with ``or 0`` — a host who DOES set
# ``attack_bonus`` is completely unaffected (confirmed: zero other test in
# the suite sets both ``weapon_proficiencies`` and relies on the old
# zero-override quirk).


def test_attack_bonus_field_not_set_yields_none_on_combatant():
    live = _start_and_attack(_party_of_one(), "c15-t1-attack-bonus-unset")
    hero = next(c for c in live.initiative if c.entity_id == "char:hero")
    assert hero.attack_bonus is None


def test_attack_bonus_field_explicitly_zero_yields_zero_on_combatant():
    live = _start_and_attack(_party_of_one(attack_bonus=0), "c15-t1-attack-bonus-zero")
    hero = next(c for c in live.initiative if c.entity_id == "char:hero")
    assert hero.attack_bonus == 0


def test_attack_bonus_unset_lets_ability_and_proficiency_drive_the_roll():
    # str 16 (+3 mod) + level-1 PB (+2) = +5. Was pinned to +0 before the fix.
    total = _attack_total(_party_of_one(), "c15-t1-attack-bonus-drives-roll")
    zeroed = _attack_total(_party_of_one(attack_bonus=0), "c15-t1-attack-bonus-zero-cmp")
    assert total - zeroed == 5


def test_attack_bonus_explicit_value_still_overrides_ability_and_proficiency():
    # A host-supplied attack_bonus is honored verbatim, unaffected by the
    # sentinel fix — byte-identical to every pre-C15 fixture.
    total = _attack_total(_party_of_one(attack_bonus=9), "c15-t1-attack-bonus-explicit")
    hero_only_total = _attack_total(
        _party_of_one(attack_bonus=9, strength=8), "c15-t1-attack-bonus-explicit-cmp"
    )
    assert total == hero_only_total
