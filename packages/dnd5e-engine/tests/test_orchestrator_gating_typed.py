"""Task 4 cutover — orchestrator PC gating reads from typed lib entities.

The three PC-side gates that previously read Avrae wrapper DICTs via
``get_asset_loader().items/.spells`` are rewired to the typed lib loader
(``get_lib_loader().get_weapon/get_spell``):

* weapon range gate (``_pc_attack_out_of_range``) — typed ``Weapon.range``;
* casting-time / spell-range gate — typed ``Spell.casting_time``/``Spell.range``;
* spell-slot gate + decrement — typed ``Spell.level``.

These tests inject a ``MemoryAssetLoader`` with one typed ``Weapon`` and a few
typed ``Spell`` instances and drive ``submit_player_intent`` end-to-end,
asserting the gate verdicts (AttackFailed/CastFailed, slot decrement,
bonus-action consumption) the typed reads must reproduce.
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
from dnd5e_srd_data.schema.common import DamagePart, Range, RangeUnits
from dnd5e_srd_data.schema.item import Weapon
from dnd5e_srd_data.schema.spell import (
    CastingTime,
    CastingTimeUnit,
    Spell,
    SpellRange,
    SpellRangeUnits,
    SpellSchool,
)

from dnd5e_engine import PlayerIntent
from dnd5e_engine.lib_loader import set_lib_loader_for_tests
from dnd5e_engine.orchestrator import (
    _get_live,
    start_combat,
    submit_player_intent,
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


def _melee_weapon(slug: str = "longsword", reach: int = 5) -> Weapon:
    return Weapon(
        slug=slug,
        name=slug.title(),
        description="A blade.",
        weight=3.0,
        cost_gp=15.0,
        rarity="common",
        provenance=_provenance(),
        review=ReviewState(),
        weapon_category="martial_melee",
        damage_parts=[DamagePart(dice="1d8", damage_type="slashing")],
        range=Range(kind="melee", value=reach, units=RangeUnits.FEET),
    )


def _ranged_weapon(slug: str = "longbow", normal: int = 30, long: int = 120) -> Weapon:
    return Weapon(
        slug=slug,
        name=slug.title(),
        description="A bow.",
        weight=2.0,
        cost_gp=50.0,
        rarity="common",
        provenance=_provenance(),
        review=ReviewState(),
        weapon_category="martial_ranged",
        damage_parts=[DamagePart(dice="1d8", damage_type="piercing")],
        range=Range(kind="ranged", value=normal, units=RangeUnits.FEET, long=long),
    )


def _spell(
    slug: str,
    *,
    level: int,
    casting_unit: CastingTimeUnit = CastingTimeUnit.ACTION,
    range_value: int | None = 120,
    range_units: SpellRangeUnits = SpellRangeUnits.FEET,
) -> Spell:
    return Spell(
        slug=slug,
        name=slug.replace("-", " ").title(),
        description="A spell.",
        level=level,
        school=SpellSchool.EVOCATION,
        casting_time=CastingTime(unit=casting_unit),
        range=SpellRange(units=range_units, value=range_value),
        duration={"units": "inst"},  # type: ignore[arg-type]
        provenance=_provenance(),
        review=ReviewState(),
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


def _party(pc_zone: str = "zone:start", **pc_overrides) -> list[PartyMemberSpec]:
    base = dict(
        entity_id="char:hero",
        name="Hero",
        initiative=20,
        hp_current=20,
        hp_max=20,
        attack_bonus=5,
        zone_id=pc_zone,
    )
    base.update(pc_overrides)
    return [PartyMemberSpec(**base)]


def _encounter(foe_zone: str = "zone:start") -> list[EncounterMemberSpec]:
    return [
        EncounterMemberSpec(
            entity_id="mon:foe",
            entity_type="Monster",
            name="Foe",
            initiative=1,
            hp_current=50,
            hp_max=50,
            zone_id=foe_zone,
        )
    ]


@pytest.fixture(autouse=True)
def _reset_lib_loader():
    yield
    set_lib_loader_for_tests(None)


# ── Weapon range gate (_pc_attack_out_of_range, ~:344) ──────────────────────


def test_melee_attack_in_reach_is_not_gated():
    """Adjacent melee target (same zone) → no AttackFailed(out_of_range)."""
    set_lib_loader_for_tests(MemoryAssetLoader(items=[_melee_weapon()]))

    async def _run():
        start = await start_combat(
            session_id="sess-melee-in",
            party=_party(),
            encounter=_encounter(foe_zone="zone:start"),
            scene_zones=_topology(),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="attack", weapon_id="longsword", target_id="mon:foe"),
        )
        return live

    live = asyncio.run(_run())
    reasons = [
        getattr(e, "reason", None) for e in live.event_log if type(e).__name__ == "AttackFailed"
    ]
    assert "out_of_range" not in reasons


def test_melee_attack_out_of_reach_is_gated():
    """Melee weapon (5ft reach), target 100ft away → AttackFailed(out_of_range)."""
    set_lib_loader_for_tests(MemoryAssetLoader(items=[_melee_weapon()]))

    async def _run():
        start = await start_combat(
            session_id="sess-melee-out",
            party=_party(pc_zone="zone:start"),
            encounter=_encounter(foe_zone="zone:far"),
            scene_zones=_topology(),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="attack", weapon_id="longsword", target_id="mon:foe"),
        )
        return live

    live = asyncio.run(_run())
    reasons = [
        getattr(e, "reason", None) for e in live.event_log if type(e).__name__ == "AttackFailed"
    ]
    assert "out_of_range" in reasons


def test_ranged_attack_in_normal_range_not_gated():
    """Ranged weapon, normal-range band reaches the target → not gated."""
    set_lib_loader_for_tests(MemoryAssetLoader(items=[_ranged_weapon(normal=30)]))

    async def _run():
        start = await start_combat(
            session_id="sess-ranged-in",
            party=_party(pc_zone="zone:start"),
            encounter=_encounter(foe_zone="zone:mid"),  # 5ft away
            scene_zones=_topology(),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="attack", weapon_id="longbow", target_id="mon:foe"),
        )
        return live

    live = asyncio.run(_run())
    reasons = [
        getattr(e, "reason", None) for e in live.event_log if type(e).__name__ == "AttackFailed"
    ]
    assert "out_of_range" not in reasons


def test_attack_unknown_weapon_falls_through_gate():
    """Slug absent from lib → get_weapon None → gate skipped (no crash)."""
    set_lib_loader_for_tests(MemoryAssetLoader(items=[]))

    async def _run():
        start = await start_combat(
            session_id="sess-unknown-weapon",
            party=_party(pc_zone="zone:start"),
            encounter=_encounter(foe_zone="zone:far"),
            scene_zones=_topology(),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        # Should not raise even though target is far and weapon is unknown.
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="attack", weapon_id="nonexistent", target_id="mon:foe"),
        )
        return live

    live = asyncio.run(_run())
    # Unknown weapon → range gate returns False → no out_of_range rejection.
    reasons = [
        getattr(e, "reason", None) for e in live.event_log if type(e).__name__ == "AttackFailed"
    ]
    assert "out_of_range" not in reasons


# ── Spell-slot gate + decrement (~:2560/:2617) ──────────────────────────────


def test_spell_slot_decrements_on_cast():
    """A level-1 spell cast decrements the caster's level-1 slot by one."""
    set_lib_loader_for_tests(MemoryAssetLoader(spells=[_spell("magic-missile", level=1)]))

    async def _run():
        start = await start_combat(
            session_id="sess-slot-dec",
            party=_party(spell_slots={1: 2}),
            encounter=_encounter(),
            scene_zones=_topology(),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(
                intent_type="cast_spell",
                spell_id="magic-missile",
                target_id="mon:foe",
                slot_level=1,
            ),
        )
        return live

    live = asyncio.run(_run())
    assert live.spell_slots_by_entity["char:hero"][1] == 1


def test_spell_no_slot_emits_cast_failed():
    """A level-1 spell with no level-1 slot available → CastFailed(no_slot)."""
    set_lib_loader_for_tests(MemoryAssetLoader(spells=[_spell("magic-missile", level=1)]))

    async def _run():
        start = await start_combat(
            session_id="sess-no-slot",
            party=_party(spell_slots={1: 0}),
            encounter=_encounter(),
            scene_zones=_topology(),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(
                intent_type="cast_spell",
                spell_id="magic-missile",
                target_id="mon:foe",
                slot_level=1,
            ),
        )
        return live

    live = asyncio.run(_run())
    reasons = [
        getattr(e, "reason", None) for e in live.event_log if type(e).__name__ == "CastFailed"
    ]
    assert "no_slot" in reasons


def test_cantrip_with_slot_request_is_rejected():
    """Level-0 spell + explicit slot_level → CastFailed(no_slot) (typed level read)."""
    set_lib_loader_for_tests(MemoryAssetLoader(spells=[_spell("fire-bolt", level=0)]))

    async def _run():
        start = await start_combat(
            session_id="sess-cantrip",
            party=_party(spell_slots={1: 2}),
            encounter=_encounter(),
            scene_zones=_topology(),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(
                intent_type="cast_spell",
                spell_id="fire-bolt",
                target_id="mon:foe",
                slot_level=1,
            ),
        )
        return live

    live = asyncio.run(_run())
    reasons = [
        getattr(e, "reason", None) for e in live.event_log if type(e).__name__ == "CastFailed"
    ]
    assert "no_slot" in reasons


# ── Casting-time classification + spell-range gate (~:2385) ──────────────────


def test_bonus_action_spell_keeps_turn_live():
    """A bonus-action spell consumes the bonus action and does NOT end the turn.

    The bonus-vs-action classification reads the typed ``casting_time.unit``
    (BONUS). Per SRD action economy, a bonus action keeps initiative: the
    actor stays current and retains the main action.
    """
    set_lib_loader_for_tests(
        MemoryAssetLoader(
            spells=[_spell("healing-word", level=1, casting_unit=CastingTimeUnit.BONUS)]
        )
    )

    async def _run():
        start = await start_combat(
            session_id="sess-bonus",
            party=_party(spell_slots={1: 2}),
            encounter=_encounter(),
            scene_zones=_topology(),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(
                intent_type="cast_spell",
                spell_id="healing-word",
                target_id="char:hero",
                slot_level=1,
            ),
        )
        return live

    live = asyncio.run(_run())
    hero = next(c for c in live.initiative if c.entity_id == "char:hero")
    # Turn stays on the hero (no auto-advance) and the bonus action is spent.
    assert live.initiative[live.current_turn_index].entity_id == "char:hero"
    assert hero.bonus_action_available is False
    assert hero.action_available is True


def test_action_spell_ends_turn():
    """An action spell (typed unit==ACTION) consumes the action and ends the turn."""
    set_lib_loader_for_tests(
        MemoryAssetLoader(
            spells=[_spell("magic-missile", level=1, casting_unit=CastingTimeUnit.ACTION)]
        )
    )

    async def _run():
        start = await start_combat(
            session_id="sess-action",
            party=_party(spell_slots={1: 2}),
            encounter=_encounter(),
            scene_zones=_topology(),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(
                intent_type="cast_spell",
                spell_id="magic-missile",
                target_id="mon:foe",
                slot_level=1,
            ),
        )
        return live

    live = asyncio.run(_run())
    # Action cast auto-advances the turn to the foe.
    assert live.initiative[live.current_turn_index].entity_id == "mon:foe"


def test_spell_out_of_range_emits_cast_failed():
    """A 120ft spell cast at a target 105ft away → CastFailed(out_of_range)."""
    set_lib_loader_for_tests(
        MemoryAssetLoader(spells=[_spell("magic-missile", level=1, range_value=30)])
    )

    async def _run():
        start = await start_combat(
            session_id="sess-spell-oor",
            party=_party(pc_zone="zone:start", spell_slots={1: 2}),
            encounter=_encounter(foe_zone="zone:far"),  # 105ft away
            scene_zones=_topology(),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(
                intent_type="cast_spell",
                spell_id="magic-missile",
                target_id="mon:foe",
                slot_level=1,
            ),
        )
        return live

    live = asyncio.run(_run())
    reasons = [
        getattr(e, "reason", None) for e in live.event_log if type(e).__name__ == "CastFailed"
    ]
    assert "out_of_range" in reasons
