"""C07 — Sneak Attack & feature repertoires.

Transcribed from specs/e2e-scenario-catalog.md, Cluster 7.
"""

from __future__ import annotations

import random

from dnd5e_srd_data.loader import BundledAssetLoader

from dnd5e_engine import PlayerIntent
from dnd5e_engine.activities.context import ActivityResolutionContext
from dnd5e_engine.activities.resolver import resolve_activity
from dnd5e_engine.events import DamageApplied, HealingApplied
from dnd5e_engine.orchestrator import _get_live, start_combat, submit_player_intent
from dnd5e_engine.specs import EncounterMemberSpec, PartyMemberSpec, SceneTopology
from dnd5e_engine.types.combat import Combatant
from dnd5e_engine.types.effects import ActiveEffect, ActiveEffectChange
from tests.e2e.harness import events_of, run_async, xfail_cluster


@xfail_cluster(7, "Sneak Attack & feature repertoires")
def test_c07_s01_sneak_attack_adds_bounded_extra_damage_on_advantage():
    """C07-S01: Sneak Attack adds bounded extra damage on an attack made
    with Advantage using a finesse weapon.

    SRD 5.2 §Sneak Attack (Rogue) ("Once per turn, you can deal an extra
    1d6 damage to one creature you hit with an attack roll if you have
    Advantage on the roll and the attack uses a Finesse or a Ranged
    weapon... The extra damage increases as you gain Rogue levels");
    foundry: packages/dnd5e-srd-data/raw_sources/foundry/packs/_source/classes24/rogue/class-features/sneak-attack.yml;
    canonical packages/dnd5e-srd-data/src/dnd5e_srd_data/canonical/features/sneak-attack.json
    (single `damage`-kind activity, `damage.parts[0].custom.formula =
    "@scale.rogue.sneak-attack"`); engine:
    packages/dnd5e-engine/src/dnd5e_engine/activities/attack.py
    (`resolve_attack` walks ONLY the attacking weapon's own activity
    damage parts; `mode: AdvantageMode = "normal"` hardcoded,
    `ctx.active_effects` never consulted for `flags.advantage.attack` on
    this path).
    """

    def _party():
        return [
            PartyMemberSpec(
                entity_id="char:rogue",
                name="Rogue",
                initiative=20,
                hp_current=30,
                hp_max=30,
                class_slug="rogue",
                character_level=5,
                dexterity=18,
                attack_bonus=7,
                equipment=("dagger",),
                zone_id="zone:a",
            )
        ]

    def _encounter():
        return [
            EncounterMemberSpec(
                entity_id="mon:foe",
                entity_type="Monster",
                name="Foe",
                initiative=1,
                ac=1,
                hp_current=500,
                hp_max=500,
                zone_id="zone:a",
            )
        ]

    async def _run(active_effects):
        start = await start_combat(
            session_id="e2e-c07-s01",
            party=_party(),
            encounter=_encounter(),
            scene_zones=SceneTopology(zones=["zone:a"], edges=[]),
            rng_seed=5,
            active_effects=active_effects,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:rogue",
            intent=PlayerIntent(intent_type="attack", weapon_id="dagger", target_id="mon:foe"),
        )
        return live

    live_a = run_async(_run(()))
    no_adv_total = sum(
        e.amount for e in events_of(live_a, DamageApplied) if e.target_id == "mon:foe"
    )

    adv_effect = ActiveEffect(
        id="effect:adv",
        name="adv",
        origin="test:adv",
        target_id="char:rogue",
        changes=[ActiveEffectChange(key="flags.advantage.attack", mode="override", value=True)],
    )
    live_b = run_async(_run((adv_effect,)))
    adv_total = sum(e.amount for e in events_of(live_b, DamageApplied) if e.target_id == "mon:foe")

    assert 3 <= adv_total - no_adv_total <= 18


@xfail_cluster(7, "Sneak Attack & feature repertoires")
def test_c07_s02_sneak_attack_ally_adjacent_alternative_trigger():
    """C07-S02: Sneak Attack's ally-adjacent alternative trigger (no
    Advantage required) adds the same bounded extra damage.

    SRD 5.2 §Sneak Attack (Rogue) ("You don't need Advantage on the attack
    roll if at least one of your allies is within 5 feet of the target,
    the ally doesn't have the Incapacitated condition, and you don't have
    Disadvantage on the attack roll"); canonical
    packages/dnd5e-srd-data/src/dnd5e_srd_data/canonical/features/sneak-attack.json
    (same activity as C07-S01); engine: same gap as C07-S01 —
    `activities/attack.py::resolve_attack` has no Sneak Attack rider
    injection at all, and no code anywhere in
    packages/dnd5e-engine/src/ evaluates "an ally is within 5 ft of the
    target and not Incapacitated."
    """

    async def _run(with_ally: bool):
        party = [
            PartyMemberSpec(
                entity_id="char:rogue",
                name="Rogue",
                initiative=20,
                hp_current=30,
                hp_max=30,
                class_slug="rogue",
                character_level=5,
                dexterity=18,
                attack_bonus=7,
                equipment=("dagger",),
                zone_id="zone:melee",
            )
        ]
        if with_ally:
            party.append(
                PartyMemberSpec(
                    entity_id="char:ally",
                    name="Ally",
                    initiative=15,
                    hp_current=10,
                    hp_max=10,
                    zone_id="zone:melee",
                )
            )
        start = await start_combat(
            session_id="e2e-c07-s02",
            party=party,
            encounter=[
                EncounterMemberSpec(
                    entity_id="mon:foe",
                    entity_type="Monster",
                    name="Foe",
                    initiative=1,
                    ac=1,
                    hp_current=500,
                    hp_max=500,
                    zone_id="zone:melee",
                )
            ],
            scene_zones=SceneTopology(zones=["zone:melee"], edges=[]),
            rng_seed=5,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:rogue",
            intent=PlayerIntent(intent_type="attack", weapon_id="dagger", target_id="mon:foe"),
        )
        return live

    live_solo = run_async(_run(with_ally=False))
    solo_total = sum(
        e.amount for e in events_of(live_solo, DamageApplied) if e.target_id == "mon:foe"
    )

    live_allied = run_async(_run(with_ally=True))
    allied_total = sum(
        e.amount for e in events_of(live_allied, DamageApplied) if e.target_id == "mon:foe"
    )

    assert 3 <= allied_total - solo_total <= 18


@xfail_cluster(7, "Sneak Attack & feature repertoires")
def test_c07_s03_channel_divinity_repertoire_needs_activity_selection():
    """C07-S03: Channel Divinity (Cleric) is a repertoire of 3 alternative
    activities; `USE_FEATURE` needs an activity-selection input.

    SRD 5.2 §Channel Divinity (Cleric) ("Each time you use this class's
    Channel Divinity, choose which Channel Divinity effect from this class
    to create": Divine Spark: Heal, Divine Spark: Save-or-damage, or Turn
    Undead); canonical
    packages/dnd5e-srd-data/src/dnd5e_srd_data/canonical/features/channel-divinity-cleric.json
    (3 activities: `UdbUwbvrWwgDuNy9` "Divine Spark: Heal", `OY9UrTXvlRL0JUoI`
    "Divine Spark: Save", `aOptL5pMaj3WtR8S` "Turn Undead"); engine:
    packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py
    (`_resolve_feature_invocation` — the `len(feature_activities) > 1`
    branch logs `feature_multi_activity_selection_deferred` and returns
    `None` UNCONDITIONALLY, before any action-economy budget is spent) and
    `PlayerIntent` (no `activity_id` field exists to disambiguate a
    choice).

    The magnitude bound [4, 11] is the resolved
    `@scale.channel-divinity-cleric.spark`d8 + WIS-mod formula at this
    caster's level (level-2 tier -> spark=1 -> `1d8 + 3`) and has a
    documented cross-dependency on C04-S02: a fix that only wires up
    activity selection but leaves the `@scale.channel-divinity-cleric.spark`
    token unresolved cannot pass this bound — it only goes green once BOTH
    C04-S02 and C07-S03 land. Transcribed as written in the catalog.
    """

    async def _run():
        start = await start_combat(
            session_id="e2e-c07-s03",
            party=[
                PartyMemberSpec(
                    entity_id="char:cleric",
                    name="Cleric",
                    initiative=20,
                    hp_current=5,
                    hp_max=20,
                    class_slug="cleric",
                    character_level=2,
                    wisdom=16,
                    zone_id="zone:a",
                )
            ],
            encounter=[
                EncounterMemberSpec(
                    entity_id="mon:foe",
                    entity_type="Monster",
                    name="Foe",
                    initiative=1,
                    ac=15,
                    hp_current=20,
                    hp_max=20,
                    zone_id="zone:a",
                )
            ],
            scene_zones=SceneTopology(zones=["zone:a"], edges=[]),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:cleric",
            intent=PlayerIntent(
                intent_type="use_feature",
                feature_id="channel-divinity-cleric",
                activity_id="UdbUwbvrWwgDuNy9",  # type: ignore[call-arg]
            ),
        )
        return live

    live = run_async(_run())
    heals = [e for e in events_of(live, HealingApplied) if e.target_id == "char:cleric"]
    assert len(heals) == 1
    assert 4 <= heals[0].amount <= 11


@xfail_cluster(7, "Sneak Attack & feature repertoires")
def test_c07_s04_sneak_attack_once_per_turn_cap_resets_next_turn():
    """C07-S04: Sneak Attack's once-per-turn cap: a second qualifying hit in
    the same turn state gains no rider; the cap resets next turn.

    SRD 5.2 §Sneak Attack (Rogue) ("Once per turn, you can deal an extra
    ... damage to one creature you hit with an attack roll..." — the
    "once per turn" clause, distinct from the Advantage/ally-adjacent
    trigger already covered by C07-S01/C07-S02); foundry / canonical:
    same sneak-attack.yml / sneak-attack.json as C07-S01/S02 (the cap is
    Foundry/5e actor-state, not activity data). Pure resolver-level probe
    (no PC multi-attack-per-turn intent path exists today — a second
    ATTACK intent in the same PC turn raises
    `IntentRejectedError("no_action_economy")` before any Sneak-Attack-
    specific logic would run — same constructibility finding as C07-S01),
    mirroring
    packages/dnd5e-engine/tests/test_orchestrator_pc_resolution_typed.py's
    pattern of building `Combatant` + `ActivityResolutionContext` directly
    and calling into the typed-Activity resolver:
    packages/dnd5e-engine/src/dnd5e_engine/activities/resolver.py
    (`resolve_activity` routes an `AttackActivity` to
    `attack.py::resolve_attack`); `attack.py::resolve_attack` /
    `_apply_on_hit_damage` (the existing sidecar-fold pattern, e.g.
    `ctx.passive_melee_damage_bonus`, a presumed `sneak_attack_spent`
    sidecar mirrors); `orchestrator.py::_emit_apply_turn_started` (the
    real per-turn reset seam this scenario's simulated "next turn" reset
    mirrors).
    """
    loader = BundledAssetLoader()
    dagger = loader.get_weapon("dagger")
    assert dagger is not None
    dagger_attack_activity = next(a for a in dagger.activities if a.id == "3SJSAL3pv9gKkAM9")

    attacker = Combatant(
        entity_id="char:rogue",
        entity_type="Character",
        name="Rogue",
        initiative=10,
        hp_current=20,
        hp_max=20,
    )
    adv_effect = ActiveEffect(
        id="effect:adv",
        name="adv",
        origin="test:adv",
        target_id="char:rogue",
        changes=[ActiveEffectChange(key="flags.advantage.attack", mode="override", value=True)],
    )

    def _hit_total(active_effects, sneak_attack_spent):
        events: list = []
        target = Combatant(
            entity_id="mon:foe",
            entity_type="Monster",
            name="Foe",
            initiative=1,
            hp_current=500,
            hp_max=500,
            ac=1,
        )
        ctx = ActivityResolutionContext(
            rng=random.Random(9),
            caster=attacker,
            targets=[target],
            event_emitter=events.append,
            caster_abilities={"str": 10, "dex": 18, "con": 10, "int": 10, "wis": 10, "cha": 10},
            caster_proficiency_bonus=3,
            caster_level=5,
            scale_values={"rogue.sneak-attack": "3d6"},
            active_effects=active_effects,  # type: ignore[call-arg]
            sneak_attack_spent=sneak_attack_spent,  # type: ignore[call-arg]
        )
        resolve_activity(dagger_attack_activity, ctx, weapon=dagger)
        return sum(
            e.amount for e in events if isinstance(e, DamageApplied) and e.target_id == "mon:foe"
        )

    baseline_total = _hit_total(active_effects=(), sneak_attack_spent={})
    hit1_total = _hit_total(active_effects=(adv_effect,), sneak_attack_spent={})
    hit2_total = _hit_total(active_effects=(adv_effect,), sneak_attack_spent={"char:rogue": True})
    hit3_total = _hit_total(active_effects=(adv_effect,), sneak_attack_spent={})

    assert 3 <= hit1_total - baseline_total <= 18
    assert hit2_total - baseline_total == 0
    assert 3 <= hit3_total - baseline_total <= 18
