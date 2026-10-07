"""C27 — monster senses and the condition clauses.

Transcribed from the local C27 scenario catalog. Every setup is a 10x10
``GridScene``; positions are ``cell(col, row)``. The senses scenarios run at
``rng_seed=7`` and the condition scenarios at ``rng_seed=1``.

SRD 5.2: Blindsight — "you can see anything that isn't behind Total Cover even
if you have the Blinded condition or are in Darkness. Moreover, in that range,
you can see something has the Invisible condition." Frightened — "You have
Disadvantage on ability checks and attack rolls while the source of fear is
within line of sight. You can't willingly move closer to the source of fear."
Poisoned — "You have Disadvantage on attack rolls and ability checks."
Petrified — "Resist Damage. You have Resistance to all damage. Poison Immunity.
You have Immunity to the Poisoned condition." Immunity — "it doesn't affect
you in any way."
"""

from __future__ import annotations

from typing import Any

import pytest

from dnd5e_engine import ActiveEffect, PlayerIntent
from dnd5e_engine.events import (
    ActorMoved,
    AttackRolled,
    CheckRolled,
    ConditionApplied,
    DamageApplied,
    EffectApplied,
    MoveFailed,
    SaveRolled,
)
from dnd5e_engine.orchestrator import (
    IntentRejectedError,
    _get_live,
    advance_monster_turn,
    start_combat,
    submit_player_intent,
)
from dnd5e_engine.specs import EncounterMemberSpec, GridScene, PartyMemberSpec
from tests.e2e.harness import cell, events_of, grid_scene, run_async


def _hero(**fields: Any) -> PartyMemberSpec:
    """``char:hero``: 30 HP, AC 12, no special sense, on 0,0; it acts after the foe."""
    base: dict[str, Any] = {
        "entity_id": "char:hero",
        "name": "Hero",
        "initiative": 1,
        "hp_current": 30,
        "hp_max": 30,
        "ac": 12,
        "zone_id": cell(0, 0),
    }
    return PartyMemberSpec(**(base | fields))


def _foe(slug: str | None = None, **fields: Any) -> EncounterMemberSpec:
    """``mon:foe`` on 1,0: 30 HP, AC 12; it acts first. ``slug`` names its template."""
    base: dict[str, Any] = {
        "entity_id": "mon:foe",
        "entity_type": "Monster",
        "name": "Foe",
        "initiative": 20,
        "hp_current": 30,
        "hp_max": 30,
        "ac": 12,
        "zone_id": cell(1, 0),
        "monster_template_slug": slug,
    }
    return EncounterMemberSpec(**(base | fields))


def _status(target_id: str, status: str, *, by: str = "mon:foe") -> ActiveEffect:
    """A seeded effect giving ``target_id`` the ``status`` condition, cast by ``by``."""
    return ActiveEffect(
        id=f"effect:{status}:{target_id}",
        name=status.title(),
        origin=f"cast:{status}:{by}",
        target_id=target_id,
        statuses={status},
    )


def _start(
    party: list[PartyMemberSpec],
    encounter: list[EncounterMemberSpec],
    *,
    session: str,
    seed: int,
    grid: GridScene | None = None,
    effects: tuple[ActiveEffect, ...] = (),
):
    async def _inner():
        start = await start_combat(
            session_id=session,
            party=party,
            encounter=encounter,
            grid_scene=grid or grid_scene(),
            rng_seed=seed,
            active_effects=list(effects),
        )
        return start.handle, _get_live(start.handle)

    return run_async(_inner())


def _act(handle, actor_id: str, **intent: Any) -> None:
    run_async(submit_player_intent(handle, actor_id=actor_id, intent=PlayerIntent(**intent)))


def _combatant(live, entity_id: str):
    return next(c for c in live.initiative if c.entity_id == entity_id)


def _holds(live, entity_id: str, condition: str) -> bool:
    """Whether either condition store (the typed one, the host's) holds ``condition``."""
    typed = {ac.condition for ac in _combatant(live, entity_id).conditions}
    return condition in typed or condition in live.active_conditions.get(entity_id, set())


# ── monster senses ───────────────────────────────────────────────────────────


def test_c27_a_templated_goblin_sees_a_hero_in_the_dark() -> None:
    # SRD 5.2 Goblin Warrior: "Senses Darkvision 60 ft."
    dark = grid_scene(lighting={cell(0, 0): "dark"})
    handle, live = _start(
        [_hero()], [_foe("goblin-warrior")], session="e2e-c27-goblin-dark", seed=7, grid=dark
    )
    run_async(advance_monster_turn(handle))
    swing = next(e for e in events_of(live, AttackRolled) if e.attacker_id == "mon:foe")
    assert swing.advantage == "normal"
    assert "unseen" not in swing.sources


def test_c27_a_bats_blindsight_sees_an_invisible_hero() -> None:
    # SRD 5.2 Bat: "Senses Blindsight 60 ft."
    handle, live = _start(
        [_hero(initiative=20)],
        [_foe("bat", initiative=1)],
        session="e2e-c27-bat-invisible",
        seed=7,
        effects=(_status("char:hero", "invisible", by="char:hero"),),
    )
    _act(handle, "char:hero", intent_type="attack", weapon_id="dagger", target_id="mon:foe")
    swing = next(e for e in events_of(live, AttackRolled) if e.attacker_id == "char:hero")
    assert swing.advantage == "normal"
    assert "condition:attacker" not in swing.sources


def test_c27_hiding_in_the_dark_fails_against_darkvision() -> None:
    dark = grid_scene(lighting={cell(0, 0): "dark"})
    handle, live = _start(
        [_hero(initiative=20)],
        [_foe("goblin-warrior", initiative=1, zone_id=cell(3, 0))],
        session="e2e-c27-hide-darkvision",
        seed=7,
        grid=dark,
    )
    with pytest.raises(IntentRejectedError) as rejected:
        _act(handle, "char:hero", intent_type="hide")
    assert rejected.value.reason == "target_invalid"
    assert events_of(live, CheckRolled) == []


def test_c27_a_blinded_bat_still_makes_an_opportunity_attack() -> None:
    handle, live = _start(
        [_hero(initiative=20)],
        [_foe("bat", initiative=1)],
        session="e2e-c27-blinded-bat",
        seed=7,
        effects=(_status("mon:foe", "blinded", by="char:hero"),),
    )
    _act(handle, "char:hero", intent_type="move", target_zone_id=cell(0, 2))
    attacks = [e for e in events_of(live, AttackRolled) if e.attacker_id == "mon:foe"]
    assert [e.is_opportunity_attack for e in attacks] == [True]
    assert live.actor_zone["char:hero"] == cell(0, 2)


def test_c27_an_explicit_senses_override_wins_over_the_template() -> None:
    dark = grid_scene(lighting={cell(0, 0): "dark"})
    # No special sense, though the goblin's stat block has Darkvision.
    handle, live = _start(
        [_hero()],
        [_foe("goblin-warrior", senses={})],
        session="e2e-c27-senses-override",
        seed=7,
        grid=dark,
    )
    run_async(advance_monster_turn(handle))
    swing = next(e for e in events_of(live, AttackRolled) if e.attacker_id == "mon:foe")
    assert (swing.advantage, swing.sources) == ("disadvantage", ["unseen"])
    # A creature with no template sees in the dark when the host says so.
    handle, live = _start(
        [_hero()],
        [_foe(attack_bonus=4, damage_dice="1d6", senses={"darkvision": 60})],
        session="e2e-c27-senses-untemplated",
        seed=7,
        grid=dark,
    )
    run_async(advance_monster_turn(handle))
    swing = next(e for e in events_of(live, AttackRolled) if e.attacker_id == "mon:foe")
    assert swing.advantage == "normal"
    assert "unseen" not in swing.sources


def _cleric_casts_contagion(foe: EncounterMemberSpec, *, session: str, effects=()):
    """A level-9 Cleric (WIS 18) beside ``foe`` touches it with Contagion at
    seed 1: the foe fails its DC 16 Constitution save. SRD 5.2 Contagion: "The
    target must succeed on a Constitution saving throw or take 11d8 Necrotic
    damage and have the Poisoned condition." """
    cleric = _hero(
        entity_id="char:cleric",
        name="Cleric",
        initiative=20,
        hp_current=60,
        hp_max=60,
        class_slug="cleric",
        character_level=9,
        wisdom=18,
        spells_known=["contagion"],
        spell_slots={5: 1},
    )
    handle, live = _start([cleric], [foe], session=session, seed=1, effects=effects)
    _act(
        handle,
        "char:cleric",
        intent_type="cast_spell",
        spell_id="contagion",
        target_id=foe.entity_id,
        slot_level=5,
    )
    assert [e.succeeded for e in events_of(live, SaveRolled)] == [False]
    return live


def test_c27_a_templated_skeleton_is_immune_to_poisoned() -> None:
    # SRD 5.2 Skeleton: "Condition Immunities Exhaustion, Poisoned".
    skeleton = _foe("skeleton", initiative=1, hp_current=200, hp_max=200)
    live = _cleric_casts_contagion(skeleton, session="e2e-c27-skeleton-poisoned")
    assert events_of(live, EffectApplied)
    assert [e for e in events_of(live, ConditionApplied) if e.condition == "poisoned"] == []
    assert not _holds(live, "mon:foe", "poisoned")


# ── condition clauses ────────────────────────────────────────────────────────


def _escape_while_frightened(*, dark: bool):
    """The bandit (no Darkvision) grapples the hero, who is Frightened of it;
    the hero tries to escape. ``dark`` puts the bandit in a dark cell."""
    grid = grid_scene(lighting={cell(1, 0): "dark"} if dark else {})
    handle, live = _start(
        [_hero()],
        [_foe("bandit")],
        session=f"e2e-c27-escape-{'dark' if dark else 'lit'}",
        seed=1,
        grid=grid,
        effects=(_status("char:hero", "frightened"),),
    )
    _act(handle, "mon:foe", intent_type="grapple", target_id="char:hero")
    assert _holds(live, "char:hero", "grappled")
    _act(handle, "char:hero", intent_type="escape_grapple")
    return next(e for e in events_of(live, CheckRolled) if e.actor_id == "char:hero")


def test_c27_escaping_a_grapple_while_frightened_of_an_unseen_source() -> None:
    unseen = _escape_while_frightened(dark=True)
    assert unseen.advantage == "normal"
    assert "condition:attacker" not in unseen.sources
    seen = _escape_while_frightened(dark=False)
    assert seen.advantage == "disadvantage"
    assert "condition:attacker" in seen.sources


def test_c27_a_poisoned_hider_rolls_stealth_at_disadvantage() -> None:
    dark = grid_scene(lighting={cell(0, 0): "dark"})
    handle, live = _start(
        [_hero(initiative=20)],
        [_foe("bandit", initiative=1, zone_id=cell(4, 0))],
        session="e2e-c27-poisoned-hide",
        seed=1,
        grid=dark,
        effects=(_status("char:hero", "poisoned"),),
    )
    _act(handle, "char:hero", intent_type="hide")
    stealth = next(e for e in events_of(live, CheckRolled) if e.skill == "stealth")
    assert stealth.advantage == "disadvantage"
    assert "condition:attacker" in stealth.sources


def test_c27_frightened_blocks_approach_to_an_unseen_source() -> None:
    dark = grid_scene(lighting={cell(5, 0): "dark"})
    handle, live = _start(
        [_hero(initiative=20)],
        [_foe("bandit", initiative=1, zone_id=cell(5, 0))],
        session="e2e-c27-frightened-approach",
        seed=1,
        grid=dark,
        effects=(_status("char:hero", "frightened"),),
    )
    _act(handle, "char:hero", intent_type="move", target_zone_id=cell(1, 0))
    assert [e.reason for e in events_of(live, MoveFailed)] == ["frightened"]
    assert events_of(live, ActorMoved) == []
    assert live.actor_zone["char:hero"] == cell(0, 0)


def _ray_of_sickness_damage(status: str) -> int:
    """A level-5 Wizard (INT 16) 15 ft from an un-templated foe with ``status``
    casts Ray of Sickness at seed 1. Petrified and Restrained both give the
    attack Advantage, so the two runs roll the same dice."""
    wizard = _hero(
        entity_id="char:wiz",
        name="Wizard",
        initiative=20,
        class_slug="wizard",
        character_level=5,
        intelligence=16,
        spells_known=["ray-of-sickness"],
        spell_slots={1: 2},
    )
    handle, live = _start(
        [wizard],
        [_foe(initiative=1, zone_id=cell(3, 0))],
        session=f"e2e-c27-ray-{status}",
        seed=1,
        effects=(_status("mon:foe", status, by="char:wiz"),),
    )
    _act(
        handle,
        "char:wiz",
        intent_type="cast_spell",
        spell_id="ray-of-sickness",
        target_id="mon:foe",
        slot_level=1,
    )
    hits = [e for e in events_of(live, AttackRolled) if e.attacker_id == "char:wiz"]
    assert [(e.advantage, e.is_hit) for e in hits] == [("advantage", True)]
    damage = [e for e in events_of(live, DamageApplied) if e.target_id == "mon:foe"]
    assert [e.damage_type for e in damage] == ["poison"]
    return damage[0].amount


def test_c27_a_petrified_creature_resists_poison_damage() -> None:
    rolled = _ray_of_sickness_damage("restrained")
    assert rolled > 1
    assert _ray_of_sickness_damage("petrified") == rolled // 2


def test_c27_a_petrified_creature_is_immune_to_poisoned() -> None:
    foe = _foe(initiative=1, hp_current=200, hp_max=200)
    live = _cleric_casts_contagion(
        foe,
        session="e2e-c27-petrified-poisoned",
        effects=(_status("mon:foe", "petrified", by="char:cleric"),),
    )
    assert events_of(live, EffectApplied)
    assert [e for e in events_of(live, ConditionApplied) if e.condition == "poisoned"] == []
    assert not _holds(live, "mon:foe", "poisoned")
    assert _holds(live, "mon:foe", "petrified")


def test_c27_a_ghost_cannot_be_grappled() -> None:
    # SRD 5.2 Ghost: "Condition Immunities ... Grappled ..."
    handle, live = _start(
        [_hero(initiative=20, strength=16)],
        [_foe("ghost", initiative=1)],
        session="e2e-c27-ghost-grapple",
        seed=1,
    )
    _act(handle, "char:hero", intent_type="grapple", target_id="mon:foe")
    assert [(e.target_id, e.succeeded) for e in events_of(live, SaveRolled)] == [("mon:foe", False)]
    assert [e for e in events_of(live, ConditionApplied) if e.condition == "grappled"] == []
    assert not _holds(live, "mon:foe", "grappled")
    assert live.active_effects.get("mon:foe", []) == []
