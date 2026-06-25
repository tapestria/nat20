"""Task 5 cutover — PC resolution routed through the typed-Activity resolver.

``submit_player_intent`` no longer builds an Avrae IR tree + ``evaluate``.
Instead it fetches the typed entity (weapon / spell / feat) from the lib
loader, builds an :class:`ActivityResolutionContext`, and walks
``resolve_activity`` over the entity's activities. These tests drive the PC
seam end-to-end against a ``MemoryAssetLoader`` and lock three contracts:

(a) a magic-missile cast emits ``DamageApplied(force)`` with NO
    ``AttackRolled``/``SaveRolled`` (auto-hit DamageActivity);
(b) STR-melee vs finesse weapon attacks produce identical ``AttackRolled``
    roll_total + ``DamageApplied`` amount for the same seed (catches a dropped
    governing-ability mod from the uniform-``caster_abilities`` reproduction);
(c) a hold-person-style cast emits ``EffectApplied`` immediately before its
    ``ConditionApplied`` in ``live.event_log[pre_event_count:]`` AND the
    orchestrator's ``_record_effect_lifecycle_links`` populates
    ``conditions_by_effect`` — so a future emit-reorder fails here, not in prod.
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
from dnd5e_srd_data.loader import BundledAssetLoader
from dnd5e_srd_data.schema.common import (
    ActivationBlock,
    AttackActivity,
    DamagePart,
    Range,
    RangeUnits,
)
from dnd5e_srd_data.schema.item import Weapon, WeaponProperty

from dnd5e_engine import PlayerIntent
from dnd5e_engine.events import (
    AttackRolled,
    ConditionApplied,
    DamageApplied,
    EffectApplied,
    SaveRolled,
)
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
from dnd5e_engine.types.conditions import ActiveCondition


def _provenance() -> Provenance:
    return Provenance(
        source="foundry",
        source_url="x",
        ingest_date=date(2026, 6, 3),
        ingest_version="v1",
        srd_version=frozenset({"5.1"}),
    )


def _attack_activity() -> AttackActivity:
    """A melee AttackActivity with an empty ability (resolver picks the
    weapon's SRD default) and no per-activity damage parts (``include_base``
    rolls the weapon's own ``damage_parts``)."""
    return AttackActivity(
        id="atk0000000000000",
        activation=ActivationBlock(type="action", value=1),
    )


def _str_melee_weapon(slug: str = "club", dice: str = "1d8") -> Weapon:
    """A plain STR-governed melee weapon (no finesse)."""
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
        damage_parts=[DamagePart(dice=dice, damage_type="slashing")],
        range=Range(kind="melee", value=5, units=RangeUnits.FEET),
        activities=[_attack_activity()],
    )


def _finesse_weapon(slug: str = "rapier", dice: str = "1d8") -> Weapon:
    """A finesse melee weapon — the resolver picks the better of STR/DEX mod.

    With the uniform ``caster_abilities`` reproduction, STR and DEX mods are
    equal, so the damage must match the STR-melee weapon exactly for the same
    seed and dice."""
    return Weapon(
        slug=slug,
        name=slug.title(),
        description="A thin blade.",
        weight=2.0,
        cost_gp=25.0,
        rarity="common",
        provenance=_provenance(),
        review=ReviewState(),
        weapon_category="martial_melee",
        properties=frozenset({WeaponProperty.FINESSE}),
        damage_parts=[DamagePart(dice=dice, damage_type="piercing")],
        range=Range(kind="melee", value=5, units=RangeUnits.FEET),
        activities=[_attack_activity()],
    )


def _topology() -> SceneTopology:
    return SceneTopology(
        zones=["zone:start"],
        edges=[ZoneEdge(a="zone:start", b="zone:start", distance_ft=0)],
    )


def _party(**pc_overrides: object) -> list[PartyMemberSpec]:
    base = dict(
        entity_id="char:hero",
        name="Hero",
        initiative=20,
        hp_current=20,
        hp_max=20,
        attack_bonus=5,
        # Equal STR/DEX (mod +3) so the finesse better-of-str/dex choice and the
        # STR default both fold in the SAME governing-ability mod — the parity
        # the weapon-attack test asserts — now off real abilities (piece 4).
        strength=16,
        dexterity=16,
        zone_id="zone:start",
    )
    base.update(pc_overrides)
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


@pytest.fixture(autouse=True)
def _reset_lib_loader():
    yield
    set_lib_loader_for_tests(None)


def _events_of(live, kind):
    return [e for e in live.event_log if isinstance(e, kind)]


# ── (a) magic-missile auto-hit cast ─────────────────────────────────────────


def test_magic_missile_cast_emits_force_damage_no_roll():
    """Magic Missile (DamageActivity, auto-hit force) → DamageApplied(force),
    no AttackRolled, no SaveRolled."""
    mm = BundledAssetLoader().get_spell("magic-missile")
    assert mm is not None
    set_lib_loader_for_tests(MemoryAssetLoader(spells=[mm]))

    async def _run():
        start = await start_combat(
            session_id="sess-mm",
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
    damage = _events_of(live, DamageApplied)
    assert damage, "Magic Missile must emit at least one DamageApplied"
    assert all(d.damage_type == "force" for d in damage)
    assert not _events_of(live, AttackRolled)
    assert not _events_of(live, SaveRolled)


# ── (b) STR-melee vs finesse weapon parity ──────────────────────────────────


def _run_weapon_attack(weapon: Weapon, slug: str):
    set_lib_loader_for_tests(MemoryAssetLoader(items=[weapon]))

    async def _run():
        start = await start_combat(
            session_id=f"sess-{slug}",
            party=_party(),
            encounter=_encounter(),
            scene_zones=_topology(),
            rng_seed=4242,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="attack", weapon_id=slug, target_id="mon:foe"),
        )
        return live

    return asyncio.run(_run())


def test_melee_and_finesse_weapon_attack_parity():
    """A STR-melee weapon and a finesse weapon with the same dice produce the
    same AttackRolled.roll_total and DamageApplied.amount for the same seed.

    Equal real STR/DEX (16 each, mod +3) makes STR == DEX mod, so the finesse
    better-of-str/dex choice and the STR default both add the same governing-
    ability mod to weapon damage. A dropped mod would diverge one path from the
    other or from the expected envelope."""
    live_str = _run_weapon_attack(_str_melee_weapon(slug="club", dice="1d8"), "club")
    live_fin = _run_weapon_attack(_finesse_weapon(slug="rapier", dice="1d8"), "rapier")

    atk_str = _events_of(live_str, AttackRolled)
    atk_fin = _events_of(live_fin, AttackRolled)
    assert atk_str, "STR-melee weapon attack must emit AttackRolled"
    assert atk_fin, "finesse weapon attack must emit AttackRolled"
    # attack_bonus_override is verbatim caster.attack_bonus for both → identical roll.
    assert atk_str[0].roll_total == atk_fin[0].roll_total

    if atk_str[0].is_hit:
        dmg_str = _events_of(live_str, DamageApplied)
        dmg_fin = _events_of(live_fin, DamageApplied)
        assert dmg_str, "STR-melee hit must emit DamageApplied"
        assert dmg_fin, "finesse hit must emit DamageApplied"
        # Same dice, same seed, equal STR/DEX mod → identical damage amount.
        assert dmg_str[0].amount == dmg_fin[0].amount
        # Mod must actually be folded in: STR/DEX 16 → mod +3; 1d8(1..8)+3.
        assert 4 <= dmg_str[0].amount <= 11


# ── (c) lifecycle EffectApplied → ConditionApplied order ────────────────────


def test_hold_person_effect_precedes_condition_and_links_recorded():
    """A hold-person cast (SaveActivity applying ``paralyzed``) emits
    EffectApplied immediately before its ConditionApplied, and the orchestrator
    records the effect→condition link in ``conditions_by_effect``.

    Seeded so the target fails the save (low DEX, deterministic RNG) and the
    paralyzed condition lands."""
    hp = BundledAssetLoader().get_spell("hold-person")
    assert hp is not None
    set_lib_loader_for_tests(MemoryAssetLoader(spells=[hp]))

    async def _run():
        start = await start_combat(
            session_id="sess-hold",
            party=_party(attack_bonus=10, spell_slots={2: 2}),
            encounter=_encounter(),
            scene_zones=_topology(),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        pre = len(live.event_log)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(
                intent_type="cast_spell",
                spell_id="hold-person",
                target_id="mon:foe",
                slot_level=2,
            ),
        )
        return live, pre

    live, pre = asyncio.run(_run())
    tail = live.event_log[pre:]
    effect_idxs = [i for i, e in enumerate(tail) if isinstance(e, EffectApplied)]
    cond_idxs = [i for i, e in enumerate(tail) if isinstance(e, ConditionApplied)]
    # The cast must have applied a condition (target failed the save).
    assert effect_idxs, "hold-person must emit EffectApplied"
    assert cond_idxs, "hold-person must emit ConditionApplied (paralyzed)"
    # EffectApplied lands immediately before its ConditionApplied.
    for ci in cond_idxs:
        assert (ci - 1) in effect_idxs, "ConditionApplied must directly follow EffectApplied"
    # The orchestrator wired the effect→condition link.
    assert live.conditions_by_effect, "_record_effect_lifecycle_links must populate the map"
    assert any("paralyzed" in conds for conds in live.conditions_by_effect.values())


def test_self_buff_cast_with_no_target_applies_effect_to_caster():
    """A self-buff cast with no ``target_id`` applies its rider to the caster.

    Regression: Shield/Mirror Image/Disguise Self are effect-bearing
    ``UtilityActivity`` spells with ``range.units == "self"``. The PC seam built
    ``targets = [c for c in initiative if c.entity_id == target_id]``, which is
    EMPTY for a targetless self-buff, so ``apply_activity_effects`` looped over
    nothing and the buff silently did nothing — no ``EffectApplied``. The seam
    now defaults the target to the caster for a self/targetless effect-bearing
    cast.
    """
    shield = BundledAssetLoader().get_spell("shield")
    assert shield is not None
    set_lib_loader_for_tests(MemoryAssetLoader(spells=[shield]))

    async def _run():
        start = await start_combat(
            session_id="sess-self-buff",
            party=_party(spell_slots={1: 2}),
            encounter=_encounter(),
            scene_zones=_topology(),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        pre = len(live.event_log)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(
                intent_type="cast_spell",
                spell_id="shield",
                target_id=None,  # self/targetless — the bug's trigger
                slot_level=1,
            ),
        )
        return live, pre

    live, pre = asyncio.run(_run())
    applied = [e for e in live.event_log[pre:] if isinstance(e, EffectApplied)]
    assert applied, "a self/targetless buff must emit EffectApplied (not a silent no-op)"
    assert all(e.effect.target_id == "char:hero" for e in applied), (
        "the buff must land on the caster, not a foe"
    )


# ── (d) AoE expansion gated on the TYPED activity's target.affects ──────────


def _two_foe_encounter() -> list[EncounterMemberSpec]:
    """Two monsters in the SAME zone as the caster — the AoE candidate set."""
    return [
        EncounterMemberSpec(
            entity_id="mon:foe",
            entity_type="Monster",
            name="Foe",
            initiative=1,
            hp_current=200,
            hp_max=200,
            zone_id="zone:start",
        ),
        EncounterMemberSpec(
            entity_id="mon:foe2",
            entity_type="Monster",
            name="Foe Two",
            initiative=0,
            hp_current=200,
            hp_max=200,
            zone_id="zone:start",
        ),
    ]


def _run_aoe_cast(slug: str):
    """Cast ``slug`` at ``mon:foe`` with two foes in-zone.

    Injects the typed spell into the lib loader; the orchestrator's AoE gate
    decides area-expansion from the typed ``target.affects`` shape alone.
    """
    spell = BundledAssetLoader().get_spell(slug)
    assert spell is not None
    set_lib_loader_for_tests(MemoryAssetLoader(spells=[spell]))

    async def _run():
        start = await start_combat(
            session_id=f"sess-aoe-{slug}",
            party=_party(attack_bonus=10, spell_slots={3: 4}),
            encounter=_two_foe_encounter(),
            scene_zones=_topology(),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(
                intent_type="cast_spell",
                spell_id=slug,
                target_id="mon:foe",
                slot_level=3,
            ),
        )
        return live

    return asyncio.run(_run())


def test_fireball_expands_to_all_in_zone():
    """Fireball — a TYPED SaveActivity with ``target.affects.count`` != "1"
    (empty ⇒ area) — saves every creature in the caster's zone (both foes),
    not just the named target."""
    live = _run_aoe_cast("fireball")
    saved = {e.target_id for e in _events_of(live, SaveRolled)}
    # The sphere catches every creature in the caster's zone (SRD: allies and
    # the caster too) — the load-bearing contract is that the NON-named foe is
    # swept in, i.e. selection went beyond the single named target.
    assert {"mon:foe", "mon:foe2"} <= saved, (
        f"fireball must roll a save for every in-zone creature, got {saved}"
    )


# ── (e) use_item intent path (restored in the cutover fix) ──────────────────


def test_use_item_resolves_item_activities():
    """A ``use_item`` intent fetches the typed Item and walks its activities.

    Net (a single-target ``SaveActivity``) forces the target's Dex save, so a
    restored ``use_item`` branch emits a ``SaveRolled`` for the named target.
    Regression for the dropped fourth resolver branch in the Task 5 cutover."""
    net = BundledAssetLoader().get_item("net")
    assert net is not None
    set_lib_loader_for_tests(MemoryAssetLoader(items=[net]))

    async def _run():
        start = await start_combat(
            session_id="sess-net",
            party=_party(attack_bonus=10),
            encounter=_encounter(),
            scene_zones=_topology(),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(
                intent_type="use_item",
                item_id="net",
                target_id="mon:foe",
            ),
        )
        return live

    live = asyncio.run(_run())
    saved = _events_of(live, SaveRolled)
    assert saved, "use_item with a save-activity item must emit a SaveRolled"
    assert {e.target_id for e in saved} == {"mon:foe"}


def test_detect_thoughts_stays_single_target_despite_large_aoe():
    """Detect Thoughts — its TYPED targeting SaveActivity is
    ``target.affects.count`` == "1" (explicit single-target). It must probe
    exactly the named target, never the whole zone. Regression for the
    over-expansion confirmed bug in the Task 5 cutover."""
    live = _run_aoe_cast("detect-thoughts")
    saved = {e.target_id for e in _events_of(live, SaveRolled)}
    assert saved == {"mon:foe"}, (
        f"detect-thoughts is single-target (affects.count=='1'); "
        f"it must not expand to the whole zone, got {saved}"
    )


# ── (g) Restrained → DEX-save disadvantage projected end-to-end (FIX 4) ──────
# Task 9-A FIX 4. The orchestrator must project a target's Restrained condition
# into the ``passive_save_dis`` save-modifier sidecar that
# ``build_activity_context`` forwards, so a single-target DEX save (Sacred Flame)
# rolls TWO d20s and keeps the lower. Locks the full chain:
# Combatant.conditions → project_passive_save_modifiers → save_modifiers payload
# → build_activity_context → save_primitive.roll_save disadvantage branch.


def test_restrained_target_dex_save_rolls_two_d20s_keeps_lower():
    """A Restrained target's DEX save (Sacred Flame, single-target ``save``)
    is rolled at disadvantage: two d20s drawn, the lower kept. We assert the
    full two-draw consumption + min by wrapping ``ctx.rng`` to log every d20."""
    sf = BundledAssetLoader().get_spell("sacred-flame")
    assert sf is not None
    assert any(a.kind == "save" for a in sf.activities)
    set_lib_loader_for_tests(MemoryAssetLoader(spells=[sf]))

    d20_draws: list[int] = []

    # A single foe, named as the cast target. Sacred Flame resolves single-
    # target (no AoE wrapper in the empty OLD loader), so exactly one DEX save
    # fires — isolating the restrained-disadvantage behavior on the foe.
    async def _run():
        start = await start_combat(
            session_id="sess-restrained-save",
            party=_party(attack_bonus=10, spell_slots={1: 4}),
            encounter=_encounter(),
            scene_zones=_topology(),
            rng_seed=7,
        )
        live = _get_live(start.handle)
        # Apply Restrained on the foe BEFORE the cast so hydration projects it.
        for idx, c in enumerate(live.initiative):
            if c.entity_id == "mon:foe":
                live.initiative[idx] = c.model_copy(
                    update={
                        "conditions": [
                            ActiveCondition(
                                condition="restrained",
                                source_entity_id="implied:scenario",
                                scope="combat",
                            )
                        ]
                    }
                )
        # Wrap the rng so every d20 face is logged in draw order.
        real_randint = live.rng.randint

        def _logged(a: int, b: int) -> int:
            v = real_randint(a, b)
            if (a, b) == (1, 20):
                d20_draws.append(v)
            return v

        live.rng.randint = _logged  # type: ignore[method-assign]
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(
                intent_type="cast_spell",
                spell_id="sacred-flame",
                target_id="mon:foe",
                slot_level=0,
            ),
        )
        return live

    live = asyncio.run(_run())
    saves = _events_of(live, SaveRolled)
    assert len(saves) == 1, f"sacred-flame is single-target, expected one save, got {saves!r}"
    assert saves[0].ability == "dex"
    # Disadvantage ⇒ exactly two d20s drawn for this one DEX save.
    assert len(d20_draws) == 2, (
        f"Restrained DEX save must draw two d20s (disadvantage), got {d20_draws!r}. "
        "One draw means the restrained-derived passive_save_dis never reached the save."
    )
    # The kept natural is the LOWER of the two draws (no save modifier on the
    # foe ⇒ roll_total == kept natural).
    assert saves[0].roll_total == min(d20_draws), (
        f"disadvantage must keep the lower d20; draws={d20_draws}, "
        f"roll_total={saves[0].roll_total}"
    )
