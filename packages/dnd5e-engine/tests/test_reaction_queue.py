"""Unit tests for the pre-armed reaction queue machinery (Cluster 6).

Covers the queue seams directly — registration (``_register_pending_reaction``),
the initiative-order drain scan (``_pop_pending_reaction``), reaction-economy
and owner-scope gating, and the typed ``ReactionTrigger`` narrowing — leaving
the full reaction resolutions to the e2e catalog tests
(tests/e2e/test_c06_reactions.py, C06-S01..S06). See
docs/dev/reaction-queue.md for the design.
"""

from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from dnd5e_engine import PlayerIntent
from dnd5e_engine.events import TurnStarted
from dnd5e_engine.orchestrator import (
    _get_live,
    _pop_pending_reaction,
    _register_pending_reaction,
    start_combat,
    submit_player_intent,
)
from dnd5e_engine.specs import EncounterMemberSpec, PartyMemberSpec, SceneTopology, ZoneEdge


def _start(session_id: str, rng_seed: int = 1):
    """Two wizard PCs (initiative 30 / 20) + one monster (initiative 1)."""

    async def _run():
        start = await start_combat(
            session_id=session_id,
            party=[
                PartyMemberSpec(
                    entity_id="char:alpha",
                    name="Alpha",
                    initiative=30,
                    hp_current=20,
                    hp_max=20,
                    intelligence=18,
                    class_slug="wizard",
                    character_level=5,
                    spells_known=["counterspell", "shield"],
                    spell_slots={1: 2, 3: 1},
                    zone_id="zone:a",
                ),
                PartyMemberSpec(
                    entity_id="char:beta",
                    name="Beta",
                    initiative=20,
                    hp_current=20,
                    hp_max=20,
                    intelligence=18,
                    class_slug="wizard",
                    character_level=5,
                    spells_known=["counterspell", "fireball"],
                    spell_slots={1: 2, 3: 2},
                    zone_id="zone:a",
                ),
            ],
            encounter=[
                EncounterMemberSpec(
                    entity_id="mon:target",
                    entity_type="Monster",
                    name="Target",
                    initiative=1,
                    hp_current=50,
                    hp_max=50,
                    ac=13,
                    zone_id="zone:b",
                )
            ],
            scene_zones=SceneTopology(
                zones=["zone:a", "zone:b"],
                edges=[ZoneEdge(a="zone:a", b="zone:b", distance_ft=30)],
            ),
            rng_seed=rng_seed,
        )
        return start.handle

    return asyncio.run(_run())


def test_ready_intent_registers_pending_reaction_and_spends_action():
    """SRD §Ready — arming spends the Action now (turn advances), registers
    the pending reaction, and draws zero dice / resolves zero activities."""
    handle = _start("rq-register")
    live = _get_live(handle)

    asyncio.run(
        submit_player_intent(
            handle,
            actor_id="char:alpha",
            intent=PlayerIntent(
                intent_type="ready",
                spell_id="counterspell",
                slot_level=3,
                reaction_trigger="cast_spell",
            ),
        )
    )

    assert len(live.pending_reactions) == 1
    pending = live.pending_reactions[0]
    assert pending.owner_id == "char:alpha"
    assert pending.trigger == "cast_spell"
    assert pending.spell_id == "counterspell"
    assert pending.slot_level == 3
    # Action spent, Reaction NOT spent (the Reaction is consumed only when
    # the trigger later fires), readied slot NOT spent at arm time.
    alpha = next(c for c in live.initiative if c.entity_id == "char:alpha")
    assert alpha.action_available is False
    assert alpha.reaction_available is True
    assert live.spell_slots_by_entity["char:alpha"][3] == 1
    # The turn advanced to the next actor (ready ends the turn like any
    # other Action).
    turn_starts = [e for e in live.event_log if isinstance(e, TurnStarted)]
    assert turn_starts[-1].actor_id == "char:beta"


def test_register_replaces_prior_entry_for_same_owner():
    """A combatant has one Action per turn — re-arming replaces, never
    stacks (docs/dev/reaction-queue.md, "Queue data structure")."""
    handle = _start("rq-replace")
    live = _get_live(handle)

    _register_pending_reaction(
        live,
        "char:alpha",
        PlayerIntent(intent_type="ready", spell_id="counterspell", reaction_trigger="cast_spell"),
    )
    _register_pending_reaction(
        live,
        "char:alpha",
        PlayerIntent(intent_type="ready", spell_id="shield", reaction_trigger="hit_by_attack"),
    )

    assert len(live.pending_reactions) == 1
    assert live.pending_reactions[0].spell_id == "shield"
    assert live.pending_reactions[0].trigger == "hit_by_attack"


def test_register_is_noop_for_other_intents_and_missing_trigger():
    handle = _start("rq-noop")
    live = _get_live(handle)

    _register_pending_reaction(
        live, "char:alpha", PlayerIntent(intent_type="ready", spell_id="shield")
    )
    _register_pending_reaction(
        live,
        "char:alpha",
        PlayerIntent(intent_type="cast_spell", spell_id="shield", reaction_trigger="hit_by_attack"),
    )

    assert live.pending_reactions == []


def test_pop_scans_initiative_order_and_excludes_triggering_actor():
    """Firing order when multiple reactions match one trigger: initiative
    order — and a caster's own pending reaction never fires for their own
    cast (SRD: a Reaction responds to another creature's trigger here)."""
    handle = _start("rq-order")
    live = _get_live(handle)

    _register_pending_reaction(
        live,
        "char:alpha",
        PlayerIntent(intent_type="ready", spell_id="counterspell", reaction_trigger="cast_spell"),
    )
    _register_pending_reaction(
        live,
        "char:beta",
        PlayerIntent(intent_type="ready", spell_id="counterspell", reaction_trigger="cast_spell"),
    )

    # Alpha (initiative 30) outranks beta (20) — but alpha IS the triggering
    # actor, so beta's reaction pops instead.
    popped = _pop_pending_reaction(live, "cast_spell", triggering_actor_id="char:alpha")
    assert popped is not None
    assert popped.owner_id == "char:beta"
    # Alpha's entry is untouched; a fresh trigger from the monster pops it
    # (initiative order: alpha before beta, but beta's is already drained).
    popped2 = _pop_pending_reaction(live, "cast_spell", triggering_actor_id="mon:target")
    assert popped2 is not None
    assert popped2.owner_id == "char:alpha"
    assert live.pending_reactions == []
    # Queue empty — nothing left to pop.
    assert _pop_pending_reaction(live, "cast_spell", triggering_actor_id="mon:target") is None


def test_pop_respects_reaction_economy_and_owner_scope():
    """A reactor without ``reaction_available`` never fires (one reaction
    per round); ``only_owner_id`` scopes hit/targeted triggers to the
    creature actually under attack — a bystander's readied reaction never
    fires for someone else's hit."""
    handle = _start("rq-economy")
    live = _get_live(handle)

    _register_pending_reaction(
        live,
        "char:alpha",
        PlayerIntent(intent_type="ready", spell_id="shield", reaction_trigger="hit_by_attack"),
    )

    # Owner scope: the attack targets beta, not alpha — no pop.
    assert (
        _pop_pending_reaction(
            live,
            "hit_by_attack",
            triggering_actor_id="mon:target",
            only_owner_id="char:beta",
        )
        is None
    )
    # Trigger mismatch: a cast_spell trigger never pops a hit_by_attack entry.
    assert _pop_pending_reaction(live, "cast_spell", triggering_actor_id="mon:target") is None

    # Reaction economy: flip reaction_available off — the armed entry stays
    # queued but cannot fire.
    for idx, c in enumerate(live.initiative):
        if c.entity_id == "char:alpha":
            live.initiative[idx] = c.model_copy(update={"reaction_available": False})
            break
    assert (
        _pop_pending_reaction(
            live,
            "hit_by_attack",
            triggering_actor_id="mon:target",
            only_owner_id="char:alpha",
        )
        is None
    )
    assert len(live.pending_reactions) == 1

    # Restore the reaction — now it pops, and is removed (fires at most once).
    for idx, c in enumerate(live.initiative):
        if c.entity_id == "char:alpha":
            live.initiative[idx] = c.model_copy(update={"reaction_available": True})
            break
    popped = _pop_pending_reaction(
        live,
        "hit_by_attack",
        triggering_actor_id="mon:target",
        only_owner_id="char:alpha",
    )
    assert popped is not None
    assert popped.owner_id == "char:alpha"
    assert live.pending_reactions == []


def test_reaction_trigger_rejects_unknown_values():
    """Typed-semantics rule: ``reaction_trigger`` is a closed
    ``ReactionTrigger`` Literal, not bare str."""
    with pytest.raises(ValidationError):
        PlayerIntent(intent_type="ready", spell_id="shield", reaction_trigger="interpretive_dance")


def test_counterspell_reactor_slot_spent_regardless_of_outcome():
    """SRD Counterspell — the COUNTERSPELLER's slot is spent whether or not
    the save succeeds; only the interrupted caster's slot is conditionally
    preserved (rng_seed=9 is C06-S01's save-succeeds branch)."""
    handle = _start("rq-reactor-slot", rng_seed=9)
    live = _get_live(handle)

    async def _script():
        await submit_player_intent(
            handle,
            actor_id="char:alpha",
            intent=PlayerIntent(
                intent_type="ready",
                spell_id="counterspell",
                slot_level=3,
                reaction_trigger="cast_spell",
            ),
        )
        await submit_player_intent(
            handle,
            actor_id="char:beta",
            intent=PlayerIntent(
                intent_type="cast_spell",
                spell_id="fireball",
                slot_level=3,
                target_id="mon:target",
            ),
        )

    asyncio.run(_script())

    # Save succeeded (seed 9) — the cast went through: beta's slot spent,
    # AND alpha's counterspell slot spent, AND alpha's reaction consumed.
    assert live.spell_slots_by_entity["char:alpha"][3] == 0
    assert live.spell_slots_by_entity["char:beta"][3] == 1
    alpha = next(c for c in live.initiative if c.entity_id == "char:alpha")
    assert alpha.reaction_available is False
    assert live.pending_reactions == []
