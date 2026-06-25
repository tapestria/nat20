"""Task 6 cutover — ``advance_monster_turn`` resolves through the typed path.

The monster turn previously selected an Avrae wrapper DICT
(``select_monster_action``), resolved it to IR
(``resolve_monster_action_to_automation``), and drove the legacy
``evaluate_automation``. It now fetches the typed ``Monster`` from the lib
loader, picks an action with ``select_typed_monster_action``, fans multiattack
out with ``expand_action_to_activities``, and resolves each returned
``Activity`` through ``resolve_activity`` — the same typed resolver the PC path
uses (Task 5).

Two behaviors are pinned here:

* multiattack fan-out — an owlbear's multiattack yields two ``AttackRolled``
  events, each against the chosen PC (mirrors
  ``backend/tests/combat/scenarios/test_goblin_multiattack.py``);
* the range gate — the monster's reach is now read from the selected action's
  typed ``AttackActivity.range`` (falling back to ``Combatant.melee_reach_ft``
  for melee), NOT the retired loader wrapper's ``range_ft``. An out-of-range
  monster still closes the distance (or skips) exactly as it did pre-cutover.
"""

from __future__ import annotations

import asyncio
from datetime import date

import pytest
from dnd5e_srd_data import (
    MemoryAssetLoader,
    Provenance,
    ReviewState,
)
from dnd5e_srd_data.schema.common import (
    AttackActivity,
    AttackDamageBlock,
    DamagePartBlock,
    RangeBlock,
    SaveActivity,
    SaveBlock,
    SaveDamageBlock,
    SaveDcBlock,
    TargetBlock,
    TargetTemplateBlock,
    UtilityActivity,
)
from dnd5e_srd_data.schema.monster import (
    AbilityScores,
    CreatureSize,
    CreatureType,
    Monster,
    MonsterAction,
    MonsterActionKind,
    Movement,
    SavingThrowProficiencies,
    Senses,
    SkillProficiencies,
)

from dnd5e_engine.events import ActorMoved, AttackRolled, IntentSubmitted, SaveRolled
from dnd5e_engine.lib_loader import set_lib_loader_for_tests
from dnd5e_engine.orchestrator import (
    _get_live,
    advance_monster_turn,
    start_combat,
)
from dnd5e_engine.specs import (
    EncounterMemberSpec,
    PartyMemberSpec,
    SceneTopology,
    ZoneEdge,
)


def _provenance() -> Provenance:
    return Provenance(
        source="foundry",
        source_url="x",
        ingest_date=date(2026, 6, 3),
        ingest_version="v1",
        srd_version=frozenset({"5.1"}),
    )


def _melee_attack(name: str, *, dice: str = "1d8", damage_type: str = "slashing") -> MonsterAction:
    """A leaf melee attack action (Foundry melee ⇒ ``range.units='self'``)."""
    return MonsterAction(
        slug=name.lower(),
        name=name,
        kind=MonsterActionKind.ACTION,
        description=f"Melee Weapon Attack. {name}.",
        activities=[
            AttackActivity(
                name=name,
                range=RangeBlock(units="self", value=None),
                damage=AttackDamageBlock(
                    parts=[DamagePartBlock(number=1, denomination=8, types=[damage_type])]
                ),
            )
        ],
    )


def _ranged_attack(name: str, *, range_ft: int) -> MonsterAction:
    """A leaf ranged attack action (Foundry ranged ⇒ ``range.units='ft'``)."""
    return MonsterAction(
        slug=name.lower(),
        name=name,
        kind=MonsterActionKind.ACTION,
        description=f"Ranged Weapon Attack. {name}.",
        activities=[
            AttackActivity(
                name=name,
                range=RangeBlock(units="ft", value=str(range_ft)),
                damage=AttackDamageBlock(
                    parts=[DamagePartBlock(number=1, denomination=6, types=["piercing"])]
                ),
            )
        ],
    )


def _breath_weapon(name: str = "Lightning Breath") -> MonsterAction:
    """A self-centered AoE save action (dragon breath shape).

    Foundry models breath weapons as a ``SaveActivity`` with
    ``range.units='self'`` and a populated ``target.template`` (the line/cone
    size). The legacy loader wrapper carried ``range_ft: 0`` for these, which
    SKIPPED the movement gate entirely — the monster never closed to melee
    reach; the save/damage resolved from its current position.
    """
    return MonsterAction(
        slug=name.lower().replace(" ", "-"),
        name=name,
        kind=MonsterActionKind.ACTION,
        description=f"{name}. Each creature in a 90-foot line must make a save.",
        activities=[
            SaveActivity(
                name=name,
                range=RangeBlock(units="self", value=None),
                target=TargetBlock(
                    template=TargetTemplateBlock(type="line", size="90", units="ft")
                ),
                save=SaveBlock(
                    ability=["dex"],
                    dc=SaveDcBlock(calculation="", formula="16"),
                ),
                damage=SaveDamageBlock(
                    on_save="half",
                    parts=[DamagePartBlock(number=10, denomination=6, types=["lightning"])],
                ),
            )
        ],
    )


def _ranged_save(name: str = "Web", *, range_ft: int = 60) -> MonsterAction:
    """A single-target ranged save action (giant-spider web / mummy dreadful-glare).

    Foundry models these as a ``SaveActivity`` with ``range.units='ft'`` and a
    real numeric ``range.value`` and an EMPTY ``target.template`` (no measured
    area). Unlike a breath weapon, this is a ranged single-target effect that
    MUST gate on its range — the monster has to be within ``range_ft`` of the
    target, closing the distance if it is not.
    """
    return MonsterAction(
        slug=name.lower().replace(" ", "-"),
        name=name,
        kind=MonsterActionKind.ACTION,
        description=f"{name}. The target must make a save.",
        activities=[
            SaveActivity(
                name=name,
                range=RangeBlock(units="ft", value=str(range_ft)),
                # Empty template: a single-target ranged save, not an area.
                target=TargetBlock(template=TargetTemplateBlock(units="ft")),
                save=SaveBlock(
                    ability=["dex"],
                    dc=SaveDcBlock(calculation="", formula="13"),
                ),
                damage=SaveDamageBlock(
                    on_save="none",
                    parts=[DamagePartBlock(number=2, denomination=6, types=["poison"])],
                ),
            )
        ],
    )


def _multiattack(count_word: str = "two") -> MonsterAction:
    """A multiattack container (no-op activities; count parsed from description)."""
    return MonsterAction(
        slug="multiattack",
        name="Multiattack",
        kind=MonsterActionKind.ACTION,
        description=f"The creature makes {count_word} attacks.",
        activities=[UtilityActivity(name="Multiattack")],
    )


def _monster(slug: str, actions: list[MonsterAction]) -> Monster:
    return Monster(
        slug=slug,
        name=slug.replace("-", " ").title(),
        description="A beast.",
        creature_type=CreatureType.BEAST,
        creature_size=CreatureSize.LARGE,
        hp=50,
        hp_dice="7d10+14",
        ability_scores=AbilityScores(str=18, dex=12, con=14, int=3, wis=12, cha=7),
        movement=Movement(walk=40),
        senses=Senses(),
        cr=3.0,
        proficiency_bonus=2,
        saving_throws=SavingThrowProficiencies(),
        skills=SkillProficiencies(),
        provenance=_provenance(),
        review=ReviewState(),
        actions=actions,
    )


def _topology() -> SceneTopology:
    # near (zone:start) <-5ft-> mid <-100ft-> far
    return SceneTopology(
        zones=["zone:start", "zone:mid", "zone:far"],
        edges=[
            ZoneEdge(a="zone:start", b="zone:mid", distance_ft=5),
            ZoneEdge(a="zone:mid", b="zone:far", distance_ft=100),
        ],
    )


def _close_topology() -> SceneTopology:
    # start <-10ft-> mid <-100ft-> far. A 5ft-reach melee monster at ``mid``
    # is out of reach (10 > 5) and must walk the 10ft edge to ``start``.
    return SceneTopology(
        zones=["zone:start", "zone:mid", "zone:far"],
        edges=[
            ZoneEdge(a="zone:start", b="zone:mid", distance_ft=10),
            ZoneEdge(a="zone:mid", b="zone:far", distance_ft=100),
        ],
    )


def _party(pc_zone: str = "zone:start") -> list[PartyMemberSpec]:
    return [
        PartyMemberSpec(
            entity_id="char:hero",
            name="Hero",
            initiative=1,  # lower than the monster so the monster acts first
            hp_current=40,
            hp_max=40,
            attack_bonus=5,
            ac=10,
            zone_id=pc_zone,
        )
    ]


def _encounter(
    slug: str,
    *,
    foe_zone: str = "zone:start",
    base_speed: int = 30,
    hp_current: int = 50,
    hp_max: int = 50,
    behavior_profile: str = "AGGRESSIVE",
) -> list[EncounterMemberSpec]:
    return [
        EncounterMemberSpec(
            entity_id="mon:foe",
            entity_type="Monster",
            name="Foe",
            initiative=20,  # acts before the PC
            hp_current=hp_current,
            hp_max=hp_max,
            ac=12,
            attack_bonus=7,
            zone_id=foe_zone,
            monster_template_slug=slug,
            base_speed=base_speed,
            behavior_profile=behavior_profile,
        )
    ]


@pytest.fixture(autouse=True)
def _reset_lib_loader():
    yield
    set_lib_loader_for_tests(None)


# ── (a) Multiattack fan-out via the typed resolver ──────────────────────────


def test_owlbear_multiattack_emits_two_attacks_at_pc():
    """An owlbear-shaped multiattack fans out to >=2 AttackRolled, each vs the PC."""
    owlbear = _monster("owlbear", [_multiattack("two"), _melee_attack("Rend")])
    set_lib_loader_for_tests(MemoryAssetLoader(monsters=[owlbear]))

    async def _run():
        start = await start_combat(
            session_id="sess-owlbear-multi",
            party=_party(),
            encounter=_encounter("owlbear", foe_zone="zone:start"),
            scene_zones=_topology(),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        await advance_monster_turn(start.handle)
        return live

    live = asyncio.run(_run())
    attacks = [e for e in live.event_log if isinstance(e, AttackRolled)]
    assert len(attacks) >= 2
    assert all(e.target_id == "char:hero" for e in attacks)


# ── (b) Typed range gate replaces the retired loader range_ft read ──────────


def test_out_of_range_melee_monster_moves_into_reach():
    """Melee monster (reach=5ft) a 10ft edge away → it MOVEs into reach, then attacks.

    Pre-cutover this used the loader wrapper's ``range_ft``; post-cutover the
    reach is read from the selected ``AttackActivity.range`` (melee ⇒ falls
    back to ``Combatant.melee_reach_ft`` = 5). Behavior is unchanged: the
    monster spends 10ft of movement to close, then swings.
    """
    monster = _monster("biter", [_melee_attack("Bite")])
    set_lib_loader_for_tests(MemoryAssetLoader(monsters=[monster]))

    async def _run():
        start = await start_combat(
            session_id="sess-melee-close",
            party=_party(pc_zone="zone:start"),
            encounter=_encounter("biter", foe_zone="zone:mid"),  # 10ft from the PC
            scene_zones=_close_topology(),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        await advance_monster_turn(start.handle)
        return live

    live = asyncio.run(_run())
    moves = [e for e in live.event_log if isinstance(e, ActorMoved) and e.actor_id == "mon:foe"]
    attacks = [e for e in live.event_log if isinstance(e, AttackRolled)]
    # It closed the 5ft gap and then attacked from reach.
    assert moves, "monster should have moved into reach"
    assert live.actor_zone["mon:foe"] == "zone:start"
    assert attacks
    assert all(e.target_id == "char:hero" for e in attacks)


def test_out_of_range_melee_monster_skips_when_cannot_reach():
    """Melee monster too slow to close the full distance → no attack this turn.

    The monster has only 5ft of speed but the target is 105ft away (5 + 100).
    It walks the first 5ft edge, still can't reach, and the attack is skipped —
    the same move-then-skip the pre-cutover ``range_ft`` gate produced.
    """
    monster = _monster("crawler", [_melee_attack("Claw")])
    set_lib_loader_for_tests(MemoryAssetLoader(monsters=[monster]))

    async def _run():
        start = await start_combat(
            session_id="sess-melee-skip",
            party=_party(pc_zone="zone:start"),
            encounter=_encounter("crawler", foe_zone="zone:far", base_speed=5),
            scene_zones=_topology(),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        await advance_monster_turn(start.handle)
        return live

    live = asyncio.run(_run())
    attacks = [e for e in live.event_log if isinstance(e, AttackRolled)]
    assert not attacks, "monster out of reach should not have attacked"


def test_ranged_monster_in_band_attacks_without_moving():
    """Ranged monster (80ft typed range) at 5ft → fires without closing.

    The 80ft typed ``AttackActivity.range`` (``units='ft'``) covers the 5ft
    gap, so the monster stays put and attacks — proving the typed range value
    (not just the melee reach fallback) drives the gate.
    """
    monster = _monster("archer", [_ranged_attack("Shortbow", range_ft=80)])
    set_lib_loader_for_tests(MemoryAssetLoader(monsters=[monster]))

    async def _run():
        start = await start_combat(
            session_id="sess-ranged-band",
            party=_party(pc_zone="zone:start"),
            encounter=_encounter("archer", foe_zone="zone:mid"),  # 5ft away
            scene_zones=_topology(),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        await advance_monster_turn(start.handle)
        return live

    live = asyncio.run(_run())
    moves = [e for e in live.event_log if isinstance(e, ActorMoved) and e.actor_id == "mon:foe"]
    attacks = [e for e in live.event_log if isinstance(e, AttackRolled)]
    assert not moves, "in-band ranged monster should not move"
    assert attacks
    assert all(e.target_id == "char:hero" for e in attacks)


def test_self_centered_breath_weapon_does_not_force_close_resolves_from_position():
    """A self-centered AoE save (dragon breath) skips the range gate entirely.

    The breath weapon is a ``SaveActivity`` with ``range.units='self'`` and a
    populated ``target.template`` (90ft line). Pre-cutover the loader wrapper
    carried ``range_ft: 0``, so the monster never moved — the save resolved
    from its current zone. Post-fix ``_monster_attack_range_ft`` returns
    ``None`` for self-centered / template / non-AttackActivity offensive
    activities, so the gate is skipped: no ``ActorMoved`` and the save fires.
    """
    dragon = _monster("breather", [_breath_weapon()])
    set_lib_loader_for_tests(MemoryAssetLoader(monsters=[dragon]))

    async def _run():
        # PC is 105ft away (5 + 100). A melee-reach reading would force a
        # multi-zone close; the self-centered breath must NOT trigger that.
        start = await start_combat(
            session_id="sess-breath-self",
            party=_party(pc_zone="zone:far"),
            encounter=_encounter("breather", foe_zone="zone:start"),
            scene_zones=_topology(),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        await advance_monster_turn(start.handle)
        return live

    live = asyncio.run(_run())
    moves = [e for e in live.event_log if isinstance(e, ActorMoved) and e.actor_id == "mon:foe"]
    saves = [e for e in live.event_log if isinstance(e, SaveRolled)]
    assert not moves, "self-centered breath weapon must not force the monster to close"
    assert live.actor_zone["mon:foe"] == "zone:start", "monster should not have moved"
    assert saves, "the breath weapon save should have resolved from position"


def test_ranged_save_monster_out_of_range_closes_distance():
    """A single-target ranged save (web, 60ft) GATES on its range and closes.

    Regression for the Task-6 over-correction: ``_monster_attack_range_ft``
    returned ``None`` for EVERY ``SaveActivity``, so a ranged single-target
    save (giant-spider web ~60ft, mummy dreadful-glare ~30ft) skipped the gate
    and fired from any distance. The web here is ``range.units='ft'``,
    ``value='60'`` with an EMPTY template — a real ranged gate. The PC is 105ft
    away (out of 60ft), so the monster must MOVE to close, exactly like an
    out-of-range attack would. Contrast ``_breath_weapon`` (self + template),
    which must NOT move.
    """
    spider = _monster("webber", [_ranged_save("Web", range_ft=60)])
    set_lib_loader_for_tests(MemoryAssetLoader(monsters=[spider]))

    async def _run():
        start = await start_combat(
            session_id="sess-web-gate",
            party=_party(pc_zone="zone:far"),  # 105ft from zone:start
            encounter=_encounter("webber", foe_zone="zone:start"),
            scene_zones=_topology(),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        await advance_monster_turn(start.handle)
        return live

    live = asyncio.run(_run())
    moves = [e for e in live.event_log if isinstance(e, ActorMoved) and e.actor_id == "mon:foe"]
    assert moves, "out-of-range ranged-save monster must close the distance (gate applies)"
    assert live.actor_zone["mon:foe"] != "zone:start", "monster should have left its start zone"


def test_wounded_aggressive_monster_below_flee_threshold_passes():
    """A wounded AGGRESSIVE monster under 10% HP passes — the flee gate fires.

    Pre-cutover ``select_monster_action`` refused to act below the
    behavior-based HP threshold (``hp_ratio < 0.10`` for AGGRESSIVE). The typed
    selector lost that gate; the fix reapplies it in ``advance_monster_turn``
    against the live ``Combatant``. At 4/50 HP (8%) the monster takes no attack
    action exactly as pre-cutover.
    """
    monster = _monster("wounded", [_melee_attack("Bite")])
    set_lib_loader_for_tests(MemoryAssetLoader(monsters=[monster]))

    async def _run():
        start = await start_combat(
            session_id="sess-flee-wounded",
            party=_party(pc_zone="zone:start"),
            encounter=_encounter(
                "wounded",
                foe_zone="zone:start",  # in reach — only the flee gate can suppress
                hp_current=4,  # 4/50 = 8% < 10% AGGRESSIVE threshold
                hp_max=50,
                behavior_profile="AGGRESSIVE",
            ),
            scene_zones=_topology(),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        await advance_monster_turn(start.handle)
        return live

    live = asyncio.run(_run())
    attacks = [e for e in live.event_log if isinstance(e, AttackRolled)]
    intents = [
        e for e in live.event_log if isinstance(e, IntentSubmitted) and e.actor_id == "mon:foe"
    ]
    assert not attacks, "wounded monster below flee threshold should not attack"
    assert intents, "the monster's turn should still record an IntentSubmitted"
    assert intents[-1].intent_type == "pass", "fleeing monster records a pass"
