"""A monster aims its own areas of effect.

SRD 5.2 stat blocks name "which creatures make the save" ("each creature in a
60-foot Cone", "each enemy in a 30-foot Emanation"); a Sphere is "centered on
a point" the monster "can see within" its range. The built-in AI places an
area where it affects the most enemies minus allies, never on itself, and only
when it affects an enemy from where the monster stands; otherwise it takes
its next option. Shield answers "being hit by an attack roll", and a
Multiattack "uses Unsettling Visage if available".
"""

from __future__ import annotations

import asyncio

import pytest
from dnd5e_srd_data.loader import BundledAssetLoader

from dnd5e_engine.events import (
    AttackRolled,
    LegendaryActionUsed,
    ReactionTriggered,
    SaveRolled,
    SpellCast,
)
from dnd5e_engine.orchestrator import (
    IntentRejectedError,
    _get_live,
    advance_monster_turn,
    start_combat,
)
from dnd5e_engine.spatial import cell_id
from dnd5e_engine.specs import GridScene
from tests.c20_support import act, combatant, events, foe, monster_turn, pc, start, wizard


def _monster(slug: str, col: int, row: int = 0, **fields):
    """A 200-HP ``slug`` at ``col,row`` that acts first (initiative 25)."""
    base = {"monster_template_slug": slug, "initiative": 25, "hp_current": 200, "hp_max": 200}
    return foe(zone_id=cell_id(col, row), **(base | fields))


def _areas(live) -> list:
    return [e for e in live.event_log if e.type == "area_targeted"]


def test_a_breath_leaves_a_readied_shield_readied() -> None:
    handle, live = start(
        [wizard(spells_known=["shield"], spell_slots={1: 1})],
        seed=1,
        encounter=[_monster("young-red-dragon", 3, 1, initiative=1)],
    )
    act(
        handle,
        "char:wiz",
        intent_type="ready",
        spell_id="shield",
        slot_level=1,
        reaction_trigger="hit_by_attack",
    )
    monster_turn(handle)
    assert [e.source_id for e in _areas(live)] == ["fire-breath"]
    assert [e.target_id for e in events(live, SaveRolled)] == ["char:wiz"]
    assert events(live, ReactionTriggered) == []
    assert [r.spell_id for r in live.pending_reactions] == ["shield"]
    assert combatant(live, "char:wiz").reaction_available is True
    assert live.spell_slots_by_entity["char:wiz"][1] == 1


def test_the_djinni_makes_three_attacks_and_raises_no_whirlwind() -> None:
    # "The djinni makes three attacks, using Storm Blade or Storm Bolt in any
    # combination" — never its Create Whirlwind, which the clause doesn't name.
    handle, live = start(
        [pc(hp_current=300, hp_max=300)], seed=1, encounter=[_monster("djinni", 1)]
    )
    monster_turn(handle)
    assert [e.attacker_id for e in events(live, AttackRolled)] == ["mon:foe"] * 3
    assert events(live, SaveRolled) == []
    assert _areas(live) == []


def test_a_mage_never_fireballs_itself() -> None:
    # 10 ft away, a Fireball centred on the hero would catch the mage: it casts
    # its next daily spell, Cone of Cold, and keeps both Fireballs.
    handle, live = start([pc()], seed=5, encounter=[_monster("mage", 2)])
    monster_turn(handle)
    assert [e.spell_id for e in events(live, SpellCast)] == ["cone-of-cold"]
    [area] = _areas(live)
    assert (area.source_id, area.shape, area.origin, area.direction) == (
        "cone-of-cold",
        "cone",
        cell_id(2, 0),
        (-1, 0),
    )
    uses = live.monster_action_uses_by_entity["mon:foe"]["spellcasting"].uses_remaining
    assert uses["spellcasting:OMMdgcswZDwcu4P9"] == 2


@pytest.mark.parametrize(("column", "spits"), [(5, True), (8, False)])
def test_a_sphere_lands_only_on_an_enemy_within_its_range(column: int, spits: bool) -> None:
    # Blinding Spittle: "a 10-foot-radius Sphere centered on a point within 30 feet".
    handle, live = start(
        [pc(zone_id=cell_id(column, 0))], seed=1, encounter=[_monster("gibbering-mouther", 0)]
    )
    monster_turn(handle)
    spittle = live.monster_action_uses_by_entity["mon:foe"]["blinding-spittle"]
    assert spittle.recharge_spent is spits
    if spits:
        [area] = _areas(live)
        assert (area.shape, area.size_ft, area.origin) == ("sphere", 10, cell_id(column, 0))
        assert [e.target_id for e in events(live, SaveRolled)] == ["char:hero"]
    else:
        assert _areas(live) == []
        assert events(live, SaveRolled) == []


def test_a_dying_pc_still_answers_each_creature_in_a_cone() -> None:
    # SRD 5.2 "Dropping to 0 Hit Points": a creature at 0 Hit Points standing
    # in a cone still makes its save (and auto-fails it, Unconscious) — the
    # breath still names it alongside a conscious ally, scored or not.
    handle, live = start(
        [
            pc(zone_id=cell_id(5, 7)),
            pc("char:down", hp_current=0, hp_max=20, zone_id=cell_id(5, 8)),
        ],
        seed=1,
        encounter=[_monster("adult-red-dragon", 5, 5)],
    )
    monster_turn(handle)
    [area] = _areas(live)
    assert (area.source_id, area.shape, area.direction) == ("fire-breath", "cone", (0, 1))
    assert set(area.affected_ids) == {"char:hero", "char:down"}


def test_an_each_enemy_area_spares_the_monsters_allies() -> None:
    # Baleful Command: "each enemy in a 30-foot Emanation originating from the rakshasa".
    handle, live = start(
        [pc(zone_id=cell_id(5, 6))],
        seed=1,
        encounter=[
            _monster("rakshasa", 5, 5),
            foe(
                entity_id="mon:kobold",
                monster_template_slug="kobold-warrior",
                zone_id=cell_id(4, 5),
            ),
        ],
    )
    monster_turn(handle)
    [area] = _areas(live)
    assert (area.source_id, area.affected_ids, area.excluded_ids) == (
        "baleful-command",
        ["char:hero"],
        ["mon:kobold"],
    )


def test_a_dying_enemy_still_answers_each_enemy_in_an_emanation() -> None:
    # Baleful Command's "each enemy" still names one at 0 Hit Points: the
    # monster's own targets (``_select_monster_targets``) score the aim, but
    # every living enemy the Emanation catches answers it, 0 HP included.
    handle, live = start(
        [
            pc(zone_id=cell_id(5, 6)),
            pc("char:down", hp_current=0, hp_max=20, zone_id=cell_id(5, 7)),
        ],
        seed=1,
        encounter=[
            _monster("rakshasa", 5, 5),
            foe(
                entity_id="mon:kobold",
                monster_template_slug="kobold-warrior",
                zone_id=cell_id(4, 5),
            ),
        ],
    )
    monster_turn(handle)
    [area] = _areas(live)
    assert (area.source_id, area.excluded_ids) == ("baleful-command", ["mon:kobold"])
    assert set(area.affected_ids) == {"char:hero", "char:down"}


def test_a_multiattack_resolves_its_area_part_against_its_area() -> None:
    # "The sphinx makes two Claw attacks and uses Roar": the claws strike its
    # target, the Roar reaches each enemy in its 500-foot Emanation. Both
    # heroes stand within 15 ft, so its daily Zone of Truth would catch the
    # sphinx itself and it takes its Multiattack.
    handle, live = start(
        [
            pc(hp_current=20, hp_max=20, zone_id=cell_id(5, 6)),
            pc("char:far", zone_id=cell_id(7, 7)),
        ],
        seed=1,
        encounter=[_monster("sphinx-of-valor", 5, 5)],
    )
    monster_turn(handle)
    assert [e.target_id for e in events(live, AttackRolled)] == ["char:hero", "char:hero"]
    [area] = _areas(live)
    assert (area.source_id, area.affected_ids) == ("roar", ["char:far", "char:hero"])


@pytest.mark.parametrize(("column", "fires"), [(0, True), (5, False)])
def test_a_multiattacks_recharge_action_is_spent_only_when_it_fires(
    column: int, fires: bool
) -> None:
    # The built-in ranking uses a charged Unsettling Visage on its own, so this
    # resolves the Multiattack's parts directly, the visage still charged. From
    # 20 ft away its 15-foot Emanation catches no one: it is skipped, unspent.
    from dnd5e_engine.activities.monster_actions import expand_action_to_parts
    from dnd5e_engine.orchestrator import _resolve_monster_parts

    _handle, live = start(
        [pc(zone_id=cell_id(column, 0))], seed=1, encounter=[_monster("doppelganger", 1)]
    )
    doppelganger = BundledAssetLoader().get_monster("doppelganger")
    assert doppelganger is not None
    multiattack = next(a for a in doppelganger.actions if a.slug == "multiattack")
    parts = expand_action_to_parts(doppelganger, multiattack, is_available=lambda _a: True)
    assert [action.slug for action, _ in parts] == ["slam", "slam", "unsettling-visage"]
    _resolve_monster_parts(live, combatant(live, "mon:foe"), combatant(live), parts)
    assert [e.source_id for e in _areas(live)] == (["unsettling-visage"] if fires else [])
    visage = live.monster_action_uses_by_entity["mon:foe"]["unsettling-visage"]
    assert visage.recharge_spent is fires


def test_a_one_creature_action_keeps_the_turns_target() -> None:
    # "The chuul makes two Pincer attacks and uses Paralyzing Tentacles" — "one
    # creature Grappled by the chuul": its template counts one creature, so it
    # resolves against the chuul's target alone, with no AreaTargeted.
    handle, live = start(
        [pc(hp_current=10, hp_max=10), pc("char:other", zone_id=cell_id(2, 1))],
        seed=1,
        encounter=[_monster("chuul", 1)],
    )
    monster_turn(handle)
    assert [e.target_id for e in events(live, AttackRolled)] == ["char:hero", "char:hero"]
    assert [(e.target_id, e.ability) for e in events(live, SaveRolled)] == [("char:hero", "con")]
    assert _areas(live) == []


def test_the_lich_never_bursts_on_itself() -> None:
    # Deathly Teleport's 10-foot burst, centred on the adjacent hero, would
    # catch the lich: its next legendary action, Disrupt Life, goes instead.
    handle, live = start([pc()], seed=1, encounter=[_monster("lich", 1, initiative=1)])
    act(handle, "char:hero", intent_type="pass")
    asyncio.run(advance_monster_turn(handle, legendary=True))
    assert [e.action_slug for e in events(live, LegendaryActionUsed)] == ["disrupt-life"]
    assert [e.source_id for e in _areas(live)] == ["disrupt-life"]


def test_a_lich_with_no_enemy_in_reach_takes_no_legendary_action() -> None:
    async def _run():
        started = await start_combat(
            session_id="c26b-lich-far",
            party=[pc()],
            encounter=[_monster("lich", 20, initiative=1)],
            grid_scene=GridScene(width=30, height=10),
            rng_seed=1,
        )
        return started.handle, _get_live(started.handle)

    handle, live = asyncio.run(_run())
    act(handle, "char:hero", intent_type="pass")
    with pytest.raises(IntentRejectedError) as refused:
        asyncio.run(advance_monster_turn(handle, legendary=True))
    assert refused.value.reason == "no_legendary_action"
    assert combatant(live, "mon:foe").legendary_actions_remaining == 3
    assert _areas(live) == []
