"""C24 — opportunity attacks through the activity context. SRD 5.2
Opportunity Attacks: "take a Reaction to make one melee attack with a weapon
or an Unarmed Strike against the provoking creature." Which attack a creature
makes (D24.8, R1), the reach it threatens (D24.3, D24.9, R2), and the
once-per-turn Sneak Attack it can deal on another creature's turn (D24.10).
All on a 10x10 grid at seed 1 (first d20: a natural 5).
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from dnd5e_engine import PlayerIntent
from dnd5e_engine.events import ActorMoved, AttackRolled, CombatantMoved, DamageApplied
from dnd5e_engine.orchestrator import (
    _find_combatant,
    _get_live,
    _LiveCombat,
    _opportunity_attackers,
    _update_combatant,
    start_combat,
    submit_player_intent,
)
from dnd5e_engine.spatial import cell_id
from dnd5e_engine.specs import EncounterMemberSpec, GridScene, PartyMemberSpec


def _hero(**fields: Any) -> PartyMemberSpec:
    base: dict[str, Any] = {
        "entity_id": "char:hero",
        "name": "Hero",
        "initiative": 1,
        "hp_current": 30,
        "hp_max": 30,
        "ac": 12,
        "strength": 14,
        "dexterity": 16,
        "zone_id": cell_id(0, 0),
    }
    return PartyMemberSpec(**(base | fields))


def _monster(entity_id: str = "mon:foe", **fields: Any) -> EncounterMemberSpec:
    """A template-less, AC 1 foe on 1,0 that acts first (any roll but a
    natural 1 hits it)."""
    base: dict[str, Any] = {
        "entity_id": entity_id,
        "entity_type": "Monster",
        "name": entity_id.removeprefix("mon:").title(),
        "initiative": 20,
        "hp_current": 100,
        "hp_max": 100,
        "ac": 1,
        "zone_id": cell_id(1, 0),
    }
    return EncounterMemberSpec(**(base | fields))


def _start(
    party: list[PartyMemberSpec], encounter: list[EncounterMemberSpec]
) -> tuple[Any, _LiveCombat]:
    async def _inner():
        result = await start_combat(
            session_id="c24-aoo-context",
            party=party,
            encounter=encounter,
            grid_scene=GridScene(width=10, height=10),
            rng_seed=1,
        )
        return result.handle, _get_live(result.handle)

    return asyncio.run(_inner())


def _act(handle: Any, actor_id: str, **intent: Any) -> None:
    asyncio.run(submit_player_intent(handle, actor_id=actor_id, intent=PlayerIntent(**intent)))


def _hero_strike(**hero: Any) -> DamageApplied:
    """The foe walks off (1,0 -> 3,0); return the damage of the hero's
    opportunity attack."""
    handle, live = _start([_hero(**hero)], [_monster()])
    _act(handle, "mon:foe", intent_type="move", target_zone_id=cell_id(3, 0))
    [aoo] = [e for e in live.event_log if isinstance(e, AttackRolled) and e.is_opportunity_attack]
    assert (aoo.attacker_id, aoo.is_hit) == ("char:hero", True)
    [damage] = [e for e in live.event_log if isinstance(e, DamageApplied)]
    return damage


def test_a_character_swings_the_first_melee_weapon_it_carries() -> None:
    damage = _hero_strike(equipment=("shortbow", "longsword"))
    assert (damage.source_id, damage.damage_type) == ("longsword", "slashing")


def test_the_opportunity_attack_weapon_wins_over_equipment() -> None:
    damage = _hero_strike(equipment=("longsword",), opportunity_attack_weapon_id="dagger")
    assert (damage.source_id, damage.damage_type) == ("dagger", "piercing")


def test_a_character_with_no_melee_weapon_makes_an_unarmed_strike() -> None:
    damage = _hero_strike(equipment=("shortbow",))
    assert (damage.source_id, damage.damage_type) == ("unarmed-strike", "bludgeoning")


@pytest.mark.parametrize("slug", ["longbow", "chain-mail", "no-such-weapon"])
def test_an_opportunity_attack_weapon_must_be_a_melee_weapon(slug: str) -> None:
    with pytest.raises(ValueError, match="char:hero opportunity_attack_weapon_id"):
        _start([_hero(opportunity_attack_weapon_id=slug)], [_monster()])


def test_a_reach_weapon_threatens_ten_feet() -> None:
    _handle, live = _start([_hero(equipment=("glaive",))], [_monster(zone_id=cell_id(2, 0))])
    # 10 ft -> 15 ft leaves a glaive's reach; 5 ft -> 10 ft stays inside it.
    assert _opportunity_attackers(
        live, mover_id="mon:foe", from_cell=cell_id(2, 0), to_cell=cell_id(3, 0)
    ) == ["char:hero"]
    assert (
        _opportunity_attackers(
            live, mover_id="mon:foe", from_cell=cell_id(1, 0), to_cell=cell_id(2, 0)
        )
        == []
    )


@pytest.mark.parametrize(
    ("slug", "reaches_ten_feet"),
    [
        # Centaur Trooper's Pike: a melee attack, "reach 10 ft."
        ("centaur-trooper", True),
        # Guard's Spear: "reach 5 ft. or range 20/60 ft." — the 20 ft is a throw.
        ("guard", False),
    ],
)
def test_a_stat_block_attack_reaches_its_melee_range_only(
    slug: str, reaches_ten_feet: bool
) -> None:
    _handle, live = _start(
        [_hero(zone_id=cell_id(2, 0))],
        [_monster(monster_template_slug=slug, zone_id=cell_id(0, 0))],
    )
    attackers = _opportunity_attackers(
        live, mover_id="char:hero", from_cell=cell_id(2, 0), to_cell=cell_id(3, 0)
    )
    assert attackers == (["mon:foe"] if reaches_ten_feet else [])


def test_a_creature_with_no_melee_attack_makes_no_opportunity_attack() -> None:
    # The Shrieker Fungus's stat block has no attack at all.
    handle, live = _start(
        [_hero(initiative=20)], [_monster(monster_template_slug="shrieker-fungus", initiative=1)]
    )
    _act(handle, "char:hero", intent_type="move", target_zone_id=cell_id(0, 2))
    assert [e for e in live.event_log if isinstance(e, AttackRolled)] == []
    shrieker = next(c for c in live.initiative if c.entity_id == "mon:foe")
    assert shrieker.reaction_available is True


def test_sneak_attack_is_once_per_turn_of_any_creature() -> None:
    # SRD 5.2 Sneak Attack: "Once per turn". The rogue spent it on its own
    # turn; the next creature's turn starts a new turn, so its opportunity
    # attack on the foe's turn — an ally beside the foe — can deal it again.
    handle, live = _start(
        [
            _hero(
                entity_id="char:rogue",
                name="Rogue",
                initiative=20,
                class_slug="rogue",
                equipment=("rapier",),
            ),
            _hero(entity_id="char:ally", name="Ally", initiative=15, zone_id=cell_id(1, 1)),
        ],
        [_monster(initiative=1)],
    )
    _update_combatant(live, "char:rogue", sneak_attack_spent_this_turn=True)
    _act(handle, "char:rogue", intent_type="pass")

    def rogue():
        return next(c for c in live.initiative if c.entity_id == "char:rogue")

    assert rogue().sneak_attack_spent_this_turn is False  # reset at the ally's turn start
    _act(handle, "char:ally", intent_type="pass")
    _act(handle, "mon:foe", intent_type="move", target_zone_id=cell_id(3, 0))
    assert rogue().sneak_attack_spent_this_turn is True  # the opportunity attack dealt it


def test_a_pushing_opportunity_attack_ends_the_walk_where_the_mover_lands() -> None:
    # SRD 5.2 Opportunity Attacks: "The attack occurs right before the
    # creature leaves your reach." A Push mastery hit carries the mover off
    # by forced movement before the walk loop would otherwise step it, so
    # the walk must end where the push landed it, not where the step aimed.
    handle, live = _start([_hero(equipment=("warhammer",))], [_monster()])
    _act(handle, "mon:foe", intent_type="move", target_zone_id=cell_id(5, 0))
    [aoo] = [e for e in live.event_log if isinstance(e, AttackRolled) and e.is_opportunity_attack]
    assert aoo.is_hit
    [moved] = [
        e for e in live.event_log if isinstance(e, CombatantMoved) and e.actor_id == "mon:foe"
    ]
    assert (moved.from_zone, moved.to_zone, moved.forced) == (cell_id(1, 0), cell_id(3, 0), True)
    assert [
        e for e in live.event_log if isinstance(e, ActorMoved) and e.actor_id == "mon:foe"
    ] == []
    assert live.actor_zone["mon:foe"] == cell_id(3, 0)
    foe = _find_combatant(live, "mon:foe")
    assert foe is not None
    assert foe.movement_remaining == 30


def test_vex_from_an_opportunity_attack_lasts_until_the_end_of_the_attackers_next_turn() -> None:
    # SRD 5.2 Vex: Advantage "before the end of your next turn" — on an
    # off-turn opportunity attack that span is only the attacker's own next
    # turn-end, not two of them.
    handle, live = _start([_hero(equipment=("rapier",))], [_monster()])
    _act(handle, "mon:foe", intent_type="move", target_zone_id=cell_id(3, 0))
    assert live.vex_grants == {"char:hero": {"mon:foe": 1}}
    _act(handle, "mon:foe", intent_type="pass")
    _act(handle, "char:hero", intent_type="pass")
    assert "char:hero" not in live.vex_grants


def test_an_unarmed_strike_at_ten_feet_rolls_no_long_range_disadvantage() -> None:
    # R2 lets an Unarmed Strike opportunity attack reach reach_ft (10 ft
    # here); the trigger already proved the target inside that reach, so it
    # is never a ranged-attack "beyond normal range" roll.
    handle, live = _start([_hero(reach_ft=10)], [_monster(zone_id=cell_id(2, 0))])
    _act(handle, "mon:foe", intent_type="move", target_zone_id=cell_id(3, 0))
    [aoo] = [e for e in live.event_log if isinstance(e, AttackRolled) and e.is_opportunity_attack]
    assert aoo.advantage == "normal"
    assert "range:long" not in aoo.sources
