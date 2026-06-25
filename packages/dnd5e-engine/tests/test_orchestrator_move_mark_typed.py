"""The Hunter's-Mark ``move_mark`` retarget gate reads the spell's range from
the typed lib loader (``Spell.range``).

The move-mark bonus-action affordance (SRD §Hunter's Mark — *"If the target
drops to 0 Hit Points before this spell ends, you can take a Bonus Action to
move the mark to a new creature you can see within range."*) gates the new
target on the spell's range. This test injects the typed lib loader with the
bundled ``hunters-mark`` Spell (90-ft FEET range) and places the new target
120 ft from the caster (out of the 90-ft range). With the typed range
observed, the orchestrator must emit ``CastFailed(reason="out_of_range")``,
proving the gate consumes the typed ``Spell.range``.
"""

from __future__ import annotations

import asyncio

import pytest
from dnd5e_srd_data import MemoryAssetLoader
from dnd5e_srd_data.loader import BundledAssetLoader

from dnd5e_engine import PlayerIntent
from dnd5e_engine.events import CastFailed, EffectApplied, EffectExpired
from dnd5e_engine.lib_loader import set_lib_loader_for_tests
from dnd5e_engine.orchestrator import (
    _MOVE_MARK_EFFECT_ID,
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

_RANGER = "char:rrrrrrrrrrrr"
_OLD_TARGET = "mon:aaaaaaaaaaaa"
_NEW_TARGET = "mon:bbbbbbbbbbbb"
_HM_ORIGIN = "spell:hunters-mark"


def _topology() -> SceneTopology:
    # Two zones 120 ft apart — beyond Hunter's-Mark's 90-ft range.
    return SceneTopology(
        zones=["zone:near", "zone:far"],
        edges=[ZoneEdge(a="zone:near", b="zone:far", distance_ft=120)],
    )


def _party() -> list[PartyMemberSpec]:
    return [
        PartyMemberSpec(
            entity_id=_RANGER,
            name="Ranger",
            initiative=20,
            hp_current=30,
            hp_max=30,
            attack_bonus=5,
            zone_id="zone:near",
            spell_slots={1: 1},
            spells_known=["hunters-mark"],
        )
    ]


def _encounter() -> list[EncounterMemberSpec]:
    return [
        # Old marked target — co-located with the caster; killed below.
        EncounterMemberSpec(
            entity_id=_OLD_TARGET,
            entity_type="Monster",
            name="Goblin A",
            initiative=10,
            hp_current=7,
            hp_max=7,
            zone_id="zone:near",
        ),
        # New target — in the far zone, 120 ft away (out of 90-ft range).
        EncounterMemberSpec(
            entity_id=_NEW_TARGET,
            entity_type="Monster",
            name="Goblin B",
            initiative=5,
            hp_current=7,
            hp_max=7,
            zone_id="zone:far",
        ),
    ]


@pytest.fixture(autouse=True)
def _reset_loaders():
    yield
    set_lib_loader_for_tests(None)


def test_move_mark_range_gate_uses_typed_spell_range() -> None:
    # Inject the typed lib loader with the bundled Hunter's Mark (90 ft FEET).
    hm = BundledAssetLoader().get_spell("hunters-mark")
    assert hm is not None
    assert hm.range.value == 90
    set_lib_loader_for_tests(MemoryAssetLoader(spells=[hm]))

    async def _run():
        start = await start_combat(
            session_id="sess-move-mark-typed",
            party=_party(),
            encounter=_encounter(),
            scene_zones=_topology(),
            rng_seed=1,
        )
        live = _get_live(start.handle)

        # Establish a live Hunter's-Mark concentration chain from the ranger
        # onto the old target, then kill the old target so the retarget is
        # legal. The new target sits in the far zone, out of 90-ft range.
        live.concentration_chain[_RANGER] = [(_OLD_TARGET, _MOVE_MARK_EFFECT_ID, _HM_ORIGIN)]
        for idx, c in enumerate(live.initiative):
            if c.entity_id == _OLD_TARGET:
                live.initiative[idx] = c.model_copy(update={"hp_current": 0, "is_alive": False})
                break

        pre = len(live.event_log)
        await submit_player_intent(
            start.handle,
            actor_id=_RANGER,
            intent=PlayerIntent(intent_type="move_mark", target_id=_NEW_TARGET),
        )
        return live, pre

    live, pre = asyncio.run(_run())
    emitted = live.event_log[pre:]

    cast_failed = [e for e in emitted if isinstance(e, CastFailed)]
    assert any(e.reason == "out_of_range" for e in cast_failed), (
        "move_mark must reject the 120-ft retarget via the typed Hunter's Mark "
        "range (90 ft). observed "
        f"CastFailed reasons = {[e.reason for e in cast_failed]!r}; all events = "
        f"{[type(e).__name__ for e in emitted]!r}."
    )

    # The retarget must NOT have re-homed the mark (no apply on the new target,
    # no expire on the old one) — the range gate blocked it.
    assert not [
        e for e in emitted if isinstance(e, EffectApplied) and e.effect.target_id == _NEW_TARGET
    ], "out-of-range retarget must not apply the mark to the new target"
    assert not [
        e for e in emitted if isinstance(e, EffectExpired) and e.target_id == _OLD_TARGET
    ], "out-of-range retarget must not expire the old mark"
