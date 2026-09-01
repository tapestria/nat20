"""C13 — timed expiry of a concentration spell's maximum duration.

SRD 5.2 §Concentration: "If the effect has a maximum duration, the effect's
description specifies how long the creator can concentrate on it: up to
1 minute, 1 hour, or some other duration." Before C13 nothing ticked this
down — a Bless cast with no damage taken never expired (BACKLOG, "Audit
2026-08-26 — spellcasting & concentration"). The counter derives from the
SPELL-level typed duration (1 round per 6 seconds, SRD §Duration): the
per-effect Foundry ``duration.rounds`` is display-only and unreliable
(Bane ships ``rounds: 1``).
"""

from __future__ import annotations

import asyncio
import random
from typing import Any, cast

from dnd5e_engine import orchestrator as orch
from dnd5e_engine.events import ConcentrationDropped, EffectApplied, EffectExpired
from dnd5e_engine.lib_loader import get_lib_loader
from dnd5e_engine.orchestrator import _LiveCombat
from dnd5e_engine.types.combat import Combatant
from dnd5e_engine.types.effects import ActiveEffect, ActiveEffectDuration


def test_concentration_max_rounds_from_typed_spell_duration() -> None:
    loader = get_lib_loader()
    assert orch._concentration_max_rounds(loader.get_spell("bless")) == 10  # 1 minute
    assert orch._concentration_max_rounds(loader.get_spell("shield-of-faith")) == 100  # 10 min
    assert orch._concentration_max_rounds(loader.get_spell("hunters-mark")) == 600  # 1 hour
    # Non-concentration and absent spells carry no engine cap.
    assert orch._concentration_max_rounds(loader.get_spell("cure-wounds")) is None
    assert orch._concentration_max_rounds(None) is None


def _live_with_counter(rounds: int) -> _LiveCombat:
    live = _LiveCombat(
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
    caster = Combatant(
        entity_id="char:a",
        entity_type="Character",
        name="A",
        initiative=10,
        hp_current=40,
        hp_max=40,
        concentration_effect_id="effect:bless",
    )
    live.initiative.append(caster)
    live.concentration_chain["char:a"] = [("char:a", "effect:bless", "cast:bless:char:a")]
    live.active_effects["char:a"] = [
        ActiveEffect(
            id="effect:bless",
            name="Bless",
            origin="cast:bless:char:a",
            target_id="char:a",
            duration=ActiveEffectDuration(seconds=60),
            flags={"concentration": True},
        )
    ]
    live.concentration_rounds_remaining["char:a"] = rounds
    return live


def test_expiry_hook_decrements_at_caster_turn_end_and_drops_at_zero() -> None:
    live = _live_with_counter(2)
    orch._hook_concentration_expiry(live, "char:a")
    assert live.concentration_rounds_remaining["char:a"] == 1
    assert not [e for e in live.event_log if isinstance(e, ConcentrationDropped)]
    orch._hook_concentration_expiry(live, "char:a")
    dropped = [e for e in live.event_log if isinstance(e, ConcentrationDropped)]
    expired = [e for e in live.event_log if isinstance(e, EffectExpired)]
    assert dropped
    assert next(iter(dropped)).target_id == "char:a"
    # Natural expiry is reason="duration", not "concentration_drop".
    assert expired
    assert next(iter(expired)).reason == "duration"
    assert "char:a" not in live.concentration_chain
    assert "char:a" not in live.concentration_rounds_remaining


def test_expiry_hook_ignores_other_actors_turn_ends() -> None:
    live = _live_with_counter(1)
    orch._hook_concentration_expiry(live, "char:someone-else")
    assert live.concentration_rounds_remaining["char:a"] == 1


def test_any_drop_clears_the_counter() -> None:
    live = _live_with_counter(5)
    orch._drop_concentration(live, "char:a")
    assert "char:a" not in live.concentration_rounds_remaining
    # And re-firing the hook after the drop is a no-op.
    orch._hook_concentration_expiry(live, "char:a")
    assert len([e for e in live.event_log if isinstance(e, ConcentrationDropped)]) == 1


def test_capless_cast_clears_inherited_counter() -> None:
    """A capless (unknown-max-duration) concentration cast must not inherit
    a stale countdown left behind by the caster's PRIOR concentration
    spell — ``_record_effect_lifecycle_links`` must be the counter's sole
    authority on every NEW concentration cast, not just capped ones.

    Preconditions model the caster's chain already having been cleared by
    some other path (e.g. a successful repeat save, or a damage-driven
    concentration break) while ``concentration_rounds_remaining`` was left
    stale — the ``prior``/``_drop_concentration`` cascade in
    ``_record_effect_lifecycle_links`` only fires when the chain is
    non-empty, so it cannot be relied on to clear the counter here; the
    ``else: pop`` branch is the only thing that can.
    """
    live = _live_with_counter(5)
    live.concentration_chain.pop("char:a", None)
    caster = live.initiative[0]
    pre_event_count = len(live.event_log)
    live.event_log.append(
        EffectApplied(
            effect=ActiveEffect(
                id="effect:shield-of-faith",
                name="Shield of Faith",
                origin="cast:shield-of-faith:char:a",
                target_id="char:a",
                duration=ActiveEffectDuration(seconds=600),
                flags={"concentration": True},
            )
        )
    )
    orch._record_effect_lifecycle_links(
        live, caster, pre_event_count, concentration_max_rounds=None
    )
    assert "char:a" not in live.concentration_rounds_remaining
    assert not [e for e in live.event_log if isinstance(e, ConcentrationDropped)]
    # The hook then no-ops: no counter left to decrement, no drop fires.
    orch._hook_concentration_expiry(live, "char:a")
    assert "char:a" not in live.concentration_rounds_remaining
    assert not [e for e in live.event_log if isinstance(e, ConcentrationDropped)]


def test_repeat_save_success_clears_counter() -> None:
    """SRD §Hold Person: a successful end-of-turn repeat save ends the
    spell on the target and, when that was the caster's last chain entry,
    must also clear the timed-expiry counter — otherwise a later
    ``engine:concentration-expiry`` turn_end tick fires a spurious drop
    against a caster who no longer concentrates on anything."""
    live = _live_with_counter(5)
    live.rng = random.Random(1)
    caster = live.initiative[0]
    identity = ("char:a", "effect:bless", "cast:bless:char:a")
    live.repeat_save_on_turn_end[identity] = [
        {
            "ability": "wis",
            "dc": -1,  # guarantee success on any d20 draw
            "effect_name": "Bless",
            "condition": "paralyzed",
            "caster_id": caster.entity_id,
        }
    ]
    orch._run_end_of_turn_saves(live, "char:a")
    assert "char:a" not in live.concentration_chain
    assert "char:a" not in live.concentration_rounds_remaining
