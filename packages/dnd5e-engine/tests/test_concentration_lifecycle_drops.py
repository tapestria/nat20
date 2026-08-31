"""C13 — concentration lifecycle drops (death, Incapacitated, one-at-a-time,
voluntary intent). SRD 5.2 §Concentration:
"Your Concentration ends if you have the Incapacitated condition or you die." /
"You lose Concentration on an effect the moment you start casting a spell that
requires Concentration…" / "The creator can end Concentration at any time (no
action required)."
"""

from __future__ import annotations

import asyncio
from typing import Any, cast

from dnd5e_engine import orchestrator as orch
from dnd5e_engine.events import (
    ConcentrationDropped,
    Death,
    EffectExpired,
)
from dnd5e_engine.orchestrator import _LiveCombat
from dnd5e_engine.types.combat import Combatant
from dnd5e_engine.types.effects import ActiveEffect, ActiveEffectDuration


def _caster(entity_id: str = "char:a") -> Combatant:
    return Combatant(
        entity_id=entity_id,
        entity_type="Character",
        name="A",
        initiative=10,
        hp_current=40,
        hp_max=40,
        character_level=5,
    )


def _fake_live() -> _LiveCombat:
    return _LiveCombat(
        handle_id="h",
        session_id="s",
        initiative=[],
        party_ids=set(),
        encounter_ids=set(),
        topology=cast(Any, None),
        rng=cast(Any, None),
        event_queue=asyncio.Queue(),
        scene_location_id="loc:test",
    )


def _concentrating_live(caster_id: str = "char:a") -> _LiveCombat:
    """A live combat where ``caster_id`` concentrates on one Bless-shaped effect."""
    live = _fake_live()
    c = _caster(caster_id).model_copy(update={"concentration_effect_id": "effect:bless"})
    live.initiative.append(c)
    live.party_ids.add(caster_id)
    identity = (caster_id, "effect:bless", f"cast:bless:{caster_id}")
    live.concentration_chain[caster_id] = [identity]
    live.active_effects[caster_id] = [
        ActiveEffect(
            id="effect:bless",
            name="Bless",
            origin=f"cast:bless:{caster_id}",
            target_id=caster_id,
            duration=ActiveEffectDuration(seconds=60),
            flags={"concentration": True},
        )
    ]
    return live


def _drop_events(live: _LiveCombat) -> tuple[list[ConcentrationDropped], list[EffectExpired]]:
    dropped = [e for e in live.event_log if isinstance(e, ConcentrationDropped)]
    expired = [
        e
        for e in live.event_log
        if isinstance(e, EffectExpired) and e.reason == "concentration_drop"
    ]
    return dropped, expired


# SRD 5.2 §Concentration: "Your Concentration ends if you have the
# Incapacitated condition or you die."
def test_record_death_drops_the_dying_casters_concentration() -> None:
    live = _concentrating_live()
    orch._record_death(live, Death(target_id="char:a", reason="damage"), killer_id=None)
    dropped, expired = _drop_events(live)
    assert dropped
    assert dropped[0].target_id == "char:a"
    assert expired
    assert expired[0].effect_id == "effect:bless"
    assert "char:a" not in live.concentration_chain


# Incapacitated glossary: "No Concentration. Your Concentration is broken."
# Unconscious/Paralyzed/Petrified/Stunned imply Incapacitated (CONDITION_IMPLIES).
def test_incapacitated_implying_condition_drops_concentration() -> None:
    for condition in ("unconscious", "paralyzed", "incapacitated", "stunned", "petrified"):
        live = _concentrating_live()
        orch._fold_condition_onto_combatant(live, "char:a", condition)
        dropped, _ = _drop_events(live)
        assert dropped, f"{condition} must break concentration"
        assert "char:a" not in live.concentration_chain


def test_non_incapacitating_condition_keeps_concentration() -> None:
    live = _concentrating_live()
    orch._fold_condition_onto_combatant(live, "char:a", "poisoned")
    dropped, _ = _drop_events(live)
    assert not dropped
    assert live.concentration_chain["char:a"]


def test_drop_cascades_once_for_simultaneous_condition_and_death() -> None:
    live = _concentrating_live()
    orch._fold_condition_onto_combatant(live, "char:a", "unconscious")
    orch._record_death(live, Death(target_id="char:a", reason="damage"), killer_id=None)
    dropped, expired = _drop_events(live)
    assert len(dropped) == 1  # second call is an idempotent no-op
    assert len(expired) == 1
