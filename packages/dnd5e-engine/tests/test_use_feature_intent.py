"""Task 3 — ``USE_FEATURE`` PC action invokes ONE granted-feature activity.

The orchestrator's feature branch resolves ``get_feature(feature_id)`` only
(no ``get_feat`` fallback), gated to the caster's class/subclass
``granted_features`` at/below the caster's level. A single-activity feature
(Rage) resolves directly; a feature outside the repertoire (a wizard invoking
``rage``) is a loud, tracked no-op; a multi-activity feature invoked without an
``activity_id`` selection defers (loud no-op) rather than firing every option.

These tests drive the real lib loader (BundledAssetLoader) so the repertoire
gate exercises the actual ``granted_features`` corpus, mirroring the
``submit_player_intent`` harness in ``test_orchestrator_pc_resolution_typed``.
"""

from __future__ import annotations

import asyncio
import logging

import pytest
from dnd5e_srd_data.loader import BundledAssetLoader

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


@pytest.fixture(autouse=True)
def _reset_lib_loader():
    # USE_FEATURE resolution reads the real granted_features corpus, so the
    # bundled loader must be the active loader for the repertoire gate.
    set_lib_loader_for_tests(BundledAssetLoader())
    yield
    set_lib_loader_for_tests(None)


def _topology() -> SceneTopology:
    return SceneTopology(
        zones=["zone:start"],
        edges=[ZoneEdge(a="zone:start", b="zone:start", distance_ft=0)],
    )


def _party(**overrides: object) -> list[PartyMemberSpec]:
    base = dict(
        entity_id="char:hero",
        name="Hero",
        initiative=20,
        hp_current=40,
        hp_max=40,
        attack_bonus=5,
        strength=18,
        constitution=16,
        character_level=5,
        class_slug="barbarian",
        zone_id="zone:start",
    )
    base.update(overrides)
    return [PartyMemberSpec(**base)]  # type: ignore[arg-type]


def _encounter() -> list[EncounterMemberSpec]:
    return [
        EncounterMemberSpec(
            entity_id="mon:foe",
            entity_type="Monster",
            name="Foe",
            initiative=1,
            hp_current=200,
            hp_max=200,
            zone_id="zone:start",
        )
    ]


def _run_use_feature(party: list[PartyMemberSpec], feature_id: str, monkeypatch=None):
    """Drive a USE_FEATURE intent. When ``monkeypatch`` is supplied, the
    activities the orchestrator routes into ``resolve_activity`` are captured
    so a test can assert exactly which (and how many) were invoked."""
    routed: list[object] = []
    if monkeypatch is not None:
        import dnd5e_engine.orchestrator as orch

        real = orch.resolve_activity

        def _spy(activity, actx, *, weapon=None):
            routed.append(activity)
            return real(activity, actx, weapon=weapon)

        monkeypatch.setattr(orch, "resolve_activity", _spy)

    async def _run():
        start = await start_combat(
            session_id=f"sess-feat-{feature_id}",
            party=party,
            encounter=_encounter(),
            scene_zones=_topology(),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        pre = len(live.event_log)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="use_feature", feature_id=feature_id),
        )
        return live, pre

    live, pre = asyncio.run(_run())
    return live, pre, routed


# ── (a) single-activity granted feature resolves ────────────────────────────


def test_rage_use_feature_resolves_single_activity(caplog, monkeypatch):
    """An L5 barbarian invoking ``feature_id="rage"`` routes Rage's SINGLE typed
    activity into ``resolve_activity`` — not a no-op (zero activities), not a
    multi-activity defer, not an all-activities fan-out."""
    with caplog.at_level(logging.WARNING):
        _live, _pre, routed = _run_use_feature(_party(), "rage", monkeypatch=monkeypatch)

    # Exactly one activity resolved — Rage's lone UtilityActivity.
    assert len(routed) == 1, f"Rage must route exactly its single activity, got {routed!r}"
    # The activity actually fired — no repertoire-rejection / multi-activity defer
    # / empty-activities warning.
    assert "feature_not_in_repertoire" not in caplog.text
    assert "feature_multi_activity_selection_deferred" not in caplog.text
    assert "class_feature_no_typed_activities" not in caplog.text


# ── (b) repertoire gate rejects an out-of-repertoire feature ────────────────


def test_wizard_invoking_rage_is_rejected(caplog, monkeypatch):
    """A wizard has no ``rage`` in ``granted_features`` → loud tracked no-op
    (``feature_not_in_repertoire``), not a resolved activity."""
    party = _party(class_slug="wizard", strength=10, character_level=5)
    with caplog.at_level(logging.WARNING):
        _live, _pre, routed = _run_use_feature(party, "rage", monkeypatch=monkeypatch)

    assert "feature_not_in_repertoire" in caplog.text
    assert not routed, "an out-of-repertoire feature must not resolve any activity"


# ── (b2) species-granted feature is accepted via the repertoire gate ────────


def test_orc_species_feature_resolves_single_activity(caplog, monkeypatch):
    """The parser routes class AND species features through USE_FEATURE. An Orc
    PC invoking its species feature ``adrenaline-rush`` (in the orc species
    ``granted_features``) must be ACCEPTED — its single typed activity routes
    into ``resolve_activity``, not rejected as out-of-repertoire."""
    # A wizard (no class grant for adrenaline-rush) whose species is orc: the
    # feature must be admitted purely on the species grant.
    party = _party(class_slug="wizard", species_slug="orc", strength=10)
    with caplog.at_level(logging.WARNING):
        _live, _pre, routed = _run_use_feature(party, "adrenaline-rush", monkeypatch=monkeypatch)

    assert len(routed) == 1, f"species feature must route its single activity, got {routed!r}"
    assert "feature_not_in_repertoire" not in caplog.text
    assert "feature_multi_activity_selection_deferred" not in caplog.text
    assert "class_feature_no_typed_activities" not in caplog.text


# ── (c) multi-activity feature without a selection defers ───────────────────


def test_multi_activity_feature_without_selection_defers(caplog, monkeypatch):
    """A cleric (channel-divinity-cleric granted at L3, 3 alternative
    activities) invoking it without an ``activity_id`` selection → loud tracked
    no-op (``feature_multi_activity_selection_deferred``), NOT all activities."""
    party = _party(
        class_slug="cleric",
        strength=10,
        constitution=12,
        character_level=5,
    )
    with caplog.at_level(logging.WARNING):
        _live, _pre, routed = _run_use_feature(
            party, "channel-divinity-cleric", monkeypatch=monkeypatch
        )

    assert "feature_multi_activity_selection_deferred" in caplog.text
    assert not routed, "a multi-activity feature must not fire any activity without a selection"


# ── (d) bonus-action economy consumed ONLY after gate + selection pass ──────


def _actor(live, entity_id="char:hero"):
    return next(c for c in live.initiative if c.entity_id == entity_id)


def test_rejected_feature_does_not_consume_bonus_action(caplog):
    """A wizard invoking ``rage`` (rejected by the repertoire gate) must NOT
    consume the Bonus Action — the BA-economy decision happens only after the
    feature passes gating and yields a concrete single activity."""
    party = _party(class_slug="wizard", strength=10, character_level=5)
    with caplog.at_level(logging.WARNING):
        live, _pre, _routed = _run_use_feature(party, "rage")

    assert "feature_not_in_repertoire" in caplog.text
    assert _actor(live).bonus_action_available is True, (
        "a gate-rejected feature must leave the Bonus Action available"
    )


def test_multi_activity_noop_does_not_consume_bonus_action(caplog):
    """A multi-activity feature invoked without a selection is a no-op and must
    consume nothing (neither Bonus Action nor Action)."""
    party = _party(
        class_slug="cleric",
        strength=10,
        constitution=12,
        character_level=5,
    )
    with caplog.at_level(logging.WARNING):
        live, _pre, _routed = _run_use_feature(party, "channel-divinity-cleric")

    assert "feature_multi_activity_selection_deferred" in caplog.text
    actor = _actor(live)
    assert actor.bonus_action_available is True
    assert actor.action_available is True


def test_valid_bonus_action_feature_consumes_bonus_action():
    """A valid bonus-action feature (Rage) DOES consume the Bonus Action while
    leaving the Action available (the rage-then-swing flow)."""
    live, _pre, _routed = _run_use_feature(_party(), "rage")
    actor = _actor(live)
    assert actor.bonus_action_available is False
    assert actor.action_available is True
