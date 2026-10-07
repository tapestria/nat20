"""C28 — feats.

Transcribed from the local C28 scenario catalog. The character-sheet
scenarios are pure ``derive_sheet`` calls on the bundled corpus; the combat
scenarios run on a 10x10 ``GridScene`` with positions ``cell(col, row)``.

SRD 5.2: "A background gives your character a specified Origin feat"; "A
feat can be taken only once unless its description states otherwise in a
"Repeatable" subsection"; Epic Boon feats need "Level 19+". Alert — "When
you roll Initiative, you can add your Proficiency Bonus to the roll."
Savage Attacker — "Once per turn when you hit a target with a weapon, you can
roll the weapon's damage dice twice and use either roll against the target."
Grappler — "You have Advantage on attack rolls against a creature Grappled
by you." Magic Initiate — "Intelligence, Wisdom, or Charisma is your
spellcasting ability for this feat's spells ... You can cast it once without
a spell slot, and you regain the ability to cast it in that way when you
finish a Long Rest."
"""

from __future__ import annotations

from typing import Any

import pytest
from dnd5e_srd_data.loader import BundledAssetLoader

from dnd5e_engine import PlayerIntent
from dnd5e_engine.build_party import build_party_member
from dnd5e_engine.build_spec import CombatInstance, DerivedSheet, derive_sheet, make_build_spec
from dnd5e_engine.events import AttackRolled, CastFailed, DamageApplied, SpellCast
from dnd5e_engine.orchestrator import (
    _get_live,
    advance_monster_turn,
    start_combat,
    submit_player_intent,
)
from dnd5e_engine.specs import EncounterMemberSpec, PartyMemberSpec
from tests.e2e.harness import cell, events_of, grid_scene, run_async, xfail_cluster

LOADER = BundledAssetLoader()


def _sheet(
    background: str | None,
    *,
    species: str = "dwarf",
    level: int = 1,
    choices: tuple[str, ...] = (),
) -> DerivedSheet:
    """A Fighter of ``level`` with ``background`` and ``choices``."""
    spec = make_build_spec(
        species_slug=species,
        class_slug="fighter",
        level=level,
        background_slug=background,
        selected_choices=choices,
    )
    return derive_sheet(spec, loader=LOADER)


def _hero(**fields: Any) -> PartyMemberSpec:
    """``char:hero``: 60 HP, on 0,0; it acts first."""
    base: dict[str, Any] = {
        "entity_id": "char:hero",
        "name": "Hero",
        "initiative": 20,
        "hp_current": 60,
        "hp_max": 60,
        "zone_id": cell(0, 0),
    }
    return PartyMemberSpec(**(base | fields))


def _foe(**fields: Any) -> EncounterMemberSpec:
    """``mon:foe`` on 1,0: 500 HP, AC 10, no template; it acts last."""
    base: dict[str, Any] = {
        "entity_id": "mon:foe",
        "entity_type": "Monster",
        "name": "Foe",
        "initiative": 1,
        "hp_current": 500,
        "hp_max": 500,
        "ac": 10,
        "zone_id": cell(1, 0),
    }
    return EncounterMemberSpec(**(base | fields))


def _start(party: list[PartyMemberSpec], encounter: list[EncounterMemberSpec], *, seed: int):
    async def _inner():
        start = await start_combat(
            session_id=f"e2e-c28-{seed}",
            party=party,
            encounter=encounter,
            grid_scene=grid_scene(),
            rng_seed=seed,
        )
        return start.handle, _get_live(start.handle)

    return run_async(_inner())


def _act(handle, actor_id: str, **intent: Any) -> None:
    run_async(submit_player_intent(handle, actor_id=actor_id, intent=PlayerIntent(**intent)))


def _combatant(live, entity_id: str):
    return next(c for c in live.initiative if c.entity_id == entity_id)


# ── the character sheet ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("background", "feat"),
    [
        ("acolyte", "magic-initiate"),
        ("criminal", "alert"),
        ("sage", "magic-initiate"),
        ("soldier", "savage-attacker"),
    ],
)
def test_c28_a_backgrounds_origin_feat_lands_on_the_sheet(background: str, feat: str) -> None:
    # SRD 5.2 backgrounds: "Feat: Magic Initiate (Cleric)", "Feat: Alert",
    # "Feat: Magic Initiate (Wizard)", "Feat: Savage Attacker".
    assert _sheet(background).feats == (feat,)


def test_c28_a_feat_is_taken_once_unless_it_is_repeatable() -> None:
    # A criminal Human picking Alert again from Versatile takes it twice.
    with pytest.raises(ValueError, match="'alert'"):
        _sheet("criminal", species="human", level=4, choices=("alert",))
    # Skilled: "Repeatable. You can take this feat more than once."
    sheet = _sheet(
        "criminal", species="human", level=4, choices=("skilled", "feat:fighter:4:skilled")
    )
    assert sheet.feats == ("alert", "skilled", "skilled")


@pytest.mark.parametrize("boon", ["boon-of-fate", "boon-of-irresistible-offense"])
def test_c28_an_epic_boon_needs_character_level_19(boon: str) -> None:
    # SRD 5.2: "Epic Boon Feat (Prerequisite: Level 19+)".
    with pytest.raises(ValueError, match="character level 19"):
        _sheet(None, level=4, choices=(f"feat:fighter:4:{boon}",))
    assert _sheet(None, level=19, choices=(f"feat:fighter:19:{boon}",)).feats == (boon,)


# ── feats in combat ──────────────────────────────────────────────────────────

_COMBAT = xfail_cluster(28, "feats in combat")


def _initiatives(seed: int, *, feats: tuple[str, ...], initiative: int | None = None):
    """Each combatant's Initiative when a level-5 hero (DEX 14) with ``feats``
    and an un-templated foe both let the engine roll."""
    hero = _hero(initiative=initiative, dexterity=14, character_level=5, feats=feats)
    _handle, live = _start([hero], [_foe(initiative=None)], seed=seed)
    return {c.entity_id: c.initiative for c in live.initiative}


@_COMBAT
def test_c28_alert_adds_the_proficiency_bonus_to_rolled_initiative() -> None:
    for seed in (1, 2, 3):
        plain = _initiatives(seed, feats=())
        alert = _initiatives(seed, feats=("alert",))
        assert alert["char:hero"] - plain["char:hero"] == 3  # level 5: Proficiency Bonus +3
        assert alert["mon:foe"] == plain["mon:foe"]
    # An Initiative the host rolled is seated as given.
    assert _initiatives(1, feats=("alert",), initiative=12)["char:hero"] == 12


def _first_hit(seed: int, *, feats: tuple[str, ...], weapon: str, **hero: Any):
    """A level-5 hero with ``feats`` swings ``weapon`` once at an AC 1 foe;
    returns the damage dealt and the live combat (the hero's turn still open:
    Extra Attack leaves it a second attack)."""
    handle, live = _start([_hero(feats=feats, **hero)], [_foe(ac=1)], seed=seed)
    _act(handle, "char:hero", intent_type="attack", weapon_id=weapon, target_id="mon:foe")
    [damage] = [e.amount for e in events_of(live, DamageApplied) if e.target_id == "mon:foe"]
    return damage, handle, live


_FIGHTER = {"class_slug": "fighter", "character_level": 5, "strength": 16}
_MONK = {"class_slug": "monk", "character_level": 5, "dexterity": 16}


@_COMBAT
def test_c28_savage_attacker_rolls_weapon_damage_twice_once_per_turn() -> None:
    higher = 0
    for seed in range(1, 21):
        plain, _, _ = _first_hit(seed, feats=(), weapon="greatsword", **_FIGHTER)
        savage, _, _ = _first_hit(seed, feats=("savage-attacker",), weapon="greatsword", **_FIGHTER)
        assert savage >= plain
        higher += savage > plain
    assert higher > 0
    _, handle, live = _first_hit(1, feats=("savage-attacker",), weapon="greatsword", **_FIGHTER)
    assert _combatant(live, "char:hero").savage_attacker_spent_this_turn is True
    # The next creature's turn is a new turn.
    _act(handle, "char:hero", intent_type="pass")
    assert _combatant(live, "char:hero").savage_attacker_spent_this_turn is False


@_COMBAT
def test_c28_savage_attacker_skips_an_unarmed_strike() -> None:
    # An Unarmed Strike is not a weapon: a Monk's rolls its Martial Arts die
    # once, and the feat is still unused for the weapon attack that follows.
    for seed in range(1, 21):
        plain, _, _ = _first_hit(seed, feats=(), weapon="unarmed-strike", **_MONK)
        savage, _, _ = _first_hit(
            seed, feats=("savage-attacker",), weapon="unarmed-strike", **_MONK
        )
        assert savage == plain
    _, handle, live = _first_hit(1, feats=("savage-attacker",), weapon="unarmed-strike", **_MONK)
    assert _combatant(live, "char:hero").savage_attacker_spent_this_turn is False
    _act(handle, "char:hero", intent_type="attack", weapon_id="shortsword", target_id="mon:foe")
    assert _combatant(live, "char:hero").savage_attacker_spent_this_turn is True


def _attack_after_grappling(*, feats: tuple[str, ...]) -> AttackRolled:
    """A Fighter 5 (STR 18) grapples the foe (its save fails at seed 1), the
    foe takes its turn, and the hero swings a longsword at it."""
    hero = _hero(feats=feats, class_slug="fighter", character_level=5, strength=18)
    handle, live = _start([hero], [_foe()], seed=1)
    _act(handle, "char:hero", intent_type="grapple", target_id="mon:foe")
    assert "grappled" in {ac.condition for ac in _combatant(live, "mon:foe").conditions}
    run_async(advance_monster_turn(handle))
    _act(handle, "char:hero", intent_type="attack", weapon_id="longsword", target_id="mon:foe")
    return next(e for e in events_of(live, AttackRolled) if e.attacker_id == "char:hero")


@_COMBAT
def test_c28_a_grappler_has_advantage_against_the_creature_it_grapples() -> None:
    swing = _attack_after_grappling(feats=("grappler",))
    assert swing.advantage == "advantage"
    assert "trait" in swing.advantage_sources
    plain = _attack_after_grappling(feats=())
    assert plain.advantage == "normal"
    assert "trait" not in plain.advantage_sources


# ── Magic Initiate ───────────────────────────────────────────────────────────

_MAGIC_INITIATE = xfail_cluster(28, "magic initiate")


def _cast_guiding_bolt(handle) -> None:
    _act(
        handle, "char:hero", intent_type="cast_spell", spell_id="guiding-bolt", target_id="mon:foe"
    )


@_MAGIC_INITIATE
def test_c28_magic_initiate_casts_its_level_1_spell_once_without_a_slot() -> None:
    # An Acolyte's Magic Initiate (Cleric), cast with Wisdom by a Fighter 1.
    member = build_party_member(
        make_build_spec(
            species_slug="dwarf",
            class_slug="fighter",
            level=1,
            background_slug="acolyte",
            ability_scores={"wisdom": 16},
            selected_choices=("magic-initiate:cleric:wis:guidance,sacred-flame:guiding-bolt",),
        ),
        CombatInstance(entity_id="char:hero", name="Hero", initiative=20, zone_id=cell(0, 0)),
        loader=LOADER,
    )
    assert member.feats == ("magic-initiate",)
    assert member.spell_slots == {}
    assert {"guidance", "sacred-flame", "guiding-bolt"} <= set(member.spells_known)
    handle, live = _start([member], [_foe(zone_id=cell(3, 0))], seed=1)
    _cast_guiding_bolt(handle)
    assert [(e.spell_id, e.slot_level) for e in events_of(live, SpellCast)] == [("guiding-bolt", 1)]
    [bolt] = [e for e in events_of(live, AttackRolled) if e.attacker_id == "char:hero"]
    assert bolt.modifier == 5  # Wisdom +3, Proficiency Bonus +2
    counters = live.custom_counters_by_entity["char:hero"]
    assert counters["slotless_cast:guiding-bolt"] == {"spent": 1}
    # Its next turn: the slotless cast is spent, and a Fighter 1 has no slot.
    run_async(advance_monster_turn(handle))
    _cast_guiding_bolt(handle)
    assert [e.reason for e in events_of(live, CastFailed)] == ["no_slot"]
    # A Long Rest restores it; a Short Rest does not.
    from dnd5e_engine.rest import recover_slotless_casts

    assert recover_slotless_casts(counters, "sr") == {"guiding-bolt": 1}
    assert recover_slotless_casts(counters, "lr") == {"guiding-bolt": 0}
