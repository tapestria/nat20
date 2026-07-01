"""Task 4 — Rage + Second Wind fire end-to-end through ``USE_FEATURE``.

* **Rage** (L5 barbarian): invoking ``feature_id="rage"`` applies its passive
  effect on the caster — the ``@scale.barbarian.rage-damage`` melee damage
  bonus resolved to ``+2`` at L5 plus the Bludgeoning/Piercing/Slashing
  resistances. A subsequent melee weapon HIT then deals +2 beyond the
  un-raged baseline (same seed); a ranged weapon attack does NOT get the +2
  (``system.bonuses.mwak.damage`` is melee-weapon-scoped).
* **Second Wind** (L5 fighter): invoking ``feature_id="second-wind"`` heals
  ``1d10 + @classes.fighter.levels`` HP on the caster (the heal-activity
  exemplar; ``@classes.fighter.levels`` resolves to 5 at L5).

These drive the real ``BundledAssetLoader`` so the repertoire gate, the rage
passive effect, the barbarian/fighter ScaleValue tables, and the real weapon
corpus are all exercised — mirroring the ``test_use_feature_intent`` harness.
"""

from __future__ import annotations

import asyncio

import pytest
from dnd5e_srd_data.loader import BundledAssetLoader

from dnd5e_engine import PlayerIntent
from dnd5e_engine.events import AttackRolled, DamageApplied, HealingApplied
from dnd5e_engine.lib_loader import set_lib_loader_for_tests
from dnd5e_engine.orchestrator import (
    _get_live,
    get_actor_active_effects,
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
    # Rage's passive effect, the barbarian/fighter ScaleValue tables, the
    # granted-features repertoire, and the weapon corpus all come from the
    # bundled loader — make it the active loader for these end-to-end flows.
    set_lib_loader_for_tests(BundledAssetLoader())
    yield
    set_lib_loader_for_tests(None)


def _topology() -> SceneTopology:
    return SceneTopology(
        zones=["zone:start"],
        edges=[ZoneEdge(a="zone:start", b="zone:start", distance_ft=0)],
    )


def _barbarian() -> list[PartyMemberSpec]:
    return [
        PartyMemberSpec(
            entity_id="char:hero",
            name="Hero",
            initiative=20,
            hp_current=40,
            hp_max=40,
            attack_bonus=5,
            strength=18,  # +4 mod
            dexterity=18,  # +4 mod so a ranged swing also hits AC 1
            constitution=16,
            character_level=5,
            class_slug="barbarian",
            zone_id="zone:start",
        )
    ]


def _fighter() -> list[PartyMemberSpec]:
    return [
        PartyMemberSpec(
            entity_id="char:hero",
            name="Hero",
            initiative=20,
            hp_current=10,
            hp_max=40,  # damaged so a heal has room to land
            attack_bonus=5,
            strength=16,
            constitution=14,
            character_level=5,
            class_slug="fighter",
            zone_id="zone:start",
        )
    ]


def _encounter() -> list[EncounterMemberSpec]:
    # AC 1 so any non-nat-1 d20 + a +4 STR mod is a guaranteed hit — the test
    # asserts the +2 rage delta, not the hit outcome.
    return [
        EncounterMemberSpec(
            entity_id="mon:foe",
            entity_type="Monster",
            name="Foe",
            initiative=1,
            hp_current=500,
            hp_max=500,
            ac=1,
            zone_id="zone:start",
        )
    ]


def _events_of(live, kind):
    return [e for e in live.event_log if isinstance(e, kind)]


def _run_melee(*, with_rage: bool, weapon_slug: str, seed: int):
    """Start a barbarian combat, optionally rage (bonus action), then swing
    ``weapon_slug`` at the foe. Return (active_effects, AttackRolled, total dmg)."""

    async def _run():
        start = await start_combat(
            session_id=f"sess-rage-{with_rage}-{weapon_slug}",
            party=_barbarian(),
            encounter=_encounter(),
            scene_zones=_topology(),
            rng_seed=seed,
        )
        live = _get_live(start.handle)
        if with_rage:
            await submit_player_intent(
                start.handle,
                actor_id="char:hero",
                intent=PlayerIntent(intent_type="use_feature", feature_id="rage"),
            )
        effects = get_actor_active_effects(start.handle, "char:hero")
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="attack", weapon_id=weapon_slug, target_id="mon:foe"),
        )
        return live, effects

    live, effects = asyncio.run(_run())
    attacks = _events_of(live, AttackRolled)
    assert attacks
    assert attacks[0].is_hit, "the AC-1 foe must be hit"
    total = sum(d.amount for d in _events_of(live, DamageApplied))
    return effects, attacks, total


# ── Rage ─────────────────────────────────────────────────────────────────────


def test_rage_applies_passive_effect_with_resolved_scale_and_resistances():
    """Invoking Rage lands the rage ActiveEffect on the caster: the
    ``@scale.barbarian.rage-damage`` melee bonus resolved to ``+2`` at L5 plus
    the three damage resistances."""
    effects, _attacks, _total = _run_melee(with_rage=True, weapon_slug="mace", seed=11)

    rage = [e for e in effects if e.name == "Rage"]
    assert rage, "Rage must apply an ActiveEffect on the caster"
    changes = {(c.key, c.value) for c in rage[0].changes}
    # @scale resolved at apply-time → the concrete +2 bonus (NOT the token).
    assert ("system.bonuses.mwak.damage", "+2") in changes, changes
    # Damage Resistance to bludgeoning / piercing / slashing.
    dr = {c.value for c in rage[0].changes if c.key == "system.traits.dr.value"}
    assert {"bludgeoning", "piercing", "slashing"} <= dr, dr


def test_rage_adds_two_to_melee_weapon_damage():
    """A raged melee swing deals exactly +2 over the un-raged baseline (same
    seed → identical base roll; the +2 is the resolved rage-damage bonus)."""
    _e_no, _a_no, base = _run_melee(with_rage=False, weapon_slug="mace", seed=11)
    _e_yes, _a_yes, raged = _run_melee(with_rage=True, weapon_slug="mace", seed=11)
    assert raged == base + 2, f"raged {raged} should be baseline {base} + 2"


def test_rage_bonus_is_melee_only_not_ranged():
    """The mwak damage bonus is melee-weapon-scoped: a ranged (shortbow) swing
    deals the SAME with or without rage."""
    _e_no, _a_no, base = _run_melee(with_rage=False, weapon_slug="shortbow", seed=11)
    _e_yes, _a_yes, raged = _run_melee(with_rage=True, weapon_slug="shortbow", seed=11)
    assert raged == base, f"ranged swing must not get rage's mwak bonus: {raged} vs {base}"


# ── Second Wind ────────────────────────────────────────────────────────────────


def test_second_wind_heals_1d10_plus_fighter_level():
    """Second Wind heals ``1d10 + @classes.fighter.levels`` — at L5 fighter the
    flat bonus resolves to +5, so the heal lands in ``[6, 15]``."""

    async def _run():
        start = await start_combat(
            session_id="sess-second-wind",
            party=_fighter(),
            encounter=_encounter(),
            scene_zones=_topology(),
            rng_seed=3,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="use_feature", feature_id="second-wind"),
        )
        return live

    live = asyncio.run(_run())
    heals = _events_of(live, HealingApplied)
    assert heals, "Second Wind must emit a HealingApplied on the caster"
    assert all(h.target_id == "char:hero" for h in heals)
    amount = sum(h.amount for h in heals)
    # 1d10 (1..10) + Fighter level 5 → 6..15. A token that failed to resolve
    # (1d10 + 0) would land in 1..10 and fail the lower bound.
    assert 6 <= amount <= 15, f"heal {amount} must be 1d10 + 5 (fighter level)"
