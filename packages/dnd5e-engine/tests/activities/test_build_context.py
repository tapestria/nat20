"""Task 2 cutover — ``build_activity_context`` from live combat state.

Locks the magnitude-reproduction contract (field-mapping table in
``docs/superpowers/plans/2026-06-03-bundled-asset-loader-cutover-plan.md``):
the new typed resolver context must reproduce the OLD Avrae path's caster
magnitudes (``attack_bonus_override``, flat ``save_dc``, uniform ``@mod``
across all six abilities) and reuse the existing per-entity passive sidecars.
"""

from __future__ import annotations

import random

from dnd5e_engine.activities.build_context import _save_dc, build_activity_context
from dnd5e_engine.activities.save_primitive import roll_save
from dnd5e_engine.types.combat import Combatant


def _caster(**overrides) -> Combatant:
    base = dict(
        entity_id="char:aaaaaaaaaaaa",
        entity_type="Character",
        name="PC",
        initiative=10,
        hp_current=20,
        attack_bonus=5,
        character_level=3,
        dexterity=14,
    )
    base.update(overrides)
    return Combatant(**base)


def _build(caster: Combatant, targets: list[Combatant], **kw):
    """Invoke build_activity_context with sensible defaults for the payload args.

    Mirrors the orchestrator cutover call: the two hydration dicts are passed
    in. Tests override ``passive_damage_modifiers`` / ``save_modifiers`` as needed.
    """
    params: dict = dict(
        rng=random.Random(1),
        event_emitter=lambda e: None,
        slot_level=1,
        base_spell_level=1,
        spellcasting_ability="int",
        concentration=False,
        source_passive_effects=[],
        spell_book={},
        passive_damage_modifiers={},
        save_modifiers={},
    )
    params.update(kw)
    return build_activity_context(caster, targets, **params)


def _monster(**overrides) -> Combatant:
    base = dict(
        entity_id="mon:bbbbbbbbbbbb",
        entity_type="Monster",
        name="Cultist",
        initiative=8,
        hp_current=15,
        attack_bonus=3,
        character_level=1,
        dexterity=12,
    )
    base.update(overrides)
    return Combatant(**base)


def test_pc_reads_real_abilities_and_level_pb():
    # PC (piece 4): per-ability mods come from the real Combatant scores, PB
    # from character_level. `_caster()` defaults str/con/int/wis/cha=10 (mod 0),
    # dexterity=14 (mod +2), character_level=3 (PB +2 = 2 + (3-1)//4).
    caster = _caster()
    ctx = _build(caster, [caster])
    assert ctx.attack_bonus_override == 5  # caster.attack_bonus verbatim
    assert ctx.caster_proficiency_bonus == 2  # PB at level 3
    # C04-S01 (Cluster 4): save_dc_override now runs the REAL SRD 5.2 formula
    # (8 + PB + spellcasting-ability mod) instead of the OLD flat
    # `8 + 2 + max(0, attack_bonus-2)` approximation. `_build`'s default
    # `spellcasting_ability="int"` + `_caster()`'s default intelligence=10
    # (mod 0) -> 8 + 2 + 0.
    assert ctx.save_dc_override == 8 + 2 + 0
    assert ctx.ability_mod("dex") == 2
    for ability in ("str", "con", "int", "wis", "cha"):
        assert ctx.ability_mod(ability) == 0


def test_pc_level5_pb_is_three():
    # PB scales with level (2 + (level-1)//4): +3 at level 5.
    caster = _caster(character_level=5)
    ctx = _build(caster, [caster])
    assert ctx.caster_proficiency_bonus == 3
    # C04-S01: the real formula, same INT-10/mod-0 caster as above -> 8 + 3 + 0.
    assert ctx.save_dc_override == 8 + 3 + 0


def test_monster_caster_magnitudes_uniform_mod_and_flat_dc():
    # Monster: mod = attack_bonus (monster_ai), save_dc = 8 + attack_bonus
    # (_monster_save_dc), uniform across all six abilities. C18 Task 5: the
    # flat approximation only applies with no resolvable
    # ``spellcasting_ability`` (the real mundane-attack call site always
    # passes ``None``) — explicit here rather than relying on ``_build``'s
    # PC-oriented "int" default, which now takes the honest stat-block-DC
    # branch for a Monster caster too.
    caster = _monster(attack_bonus=4)
    ctx = _build(caster, [caster], spellcasting_ability=None)
    assert ctx.attack_bonus_override == 4
    assert ctx.save_dc_override == 8 + 4
    for ability in ("str", "dex", "con", "int", "wis", "cha"):
        assert ctx.ability_mod(ability) == 4


def test_monster_save_dc_uses_the_stat_block_spellcasting_ability():
    """C18 Task 5: a Monster caster with a resolved ``spellcasting_ability``
    (hydrated from the SRD 5.2 stat block, not the mundane-attack flat
    approximation) uses the same honest ``8 + PB + ability mod`` formula a PC
    caster does, against ITS OWN real ability score. Pinned against the
    bundled mage (int 17 -> mod +3, PB +3 -> DC 14) and adult red dragon
    (cha 23 -> mod +6, PB +6 -> DC 20) canonical stat blocks.
    """
    mage = _monster(intelligence=17, proficiency_bonus_override=3)
    assert (
        _save_dc(
            mage,
            0,
            caster_abilities={},
            caster_proficiency_bonus=2,
            spellcasting_ability="int",
        )
        == 14
    )
    dragon = _monster(charisma=23, proficiency_bonus_override=6)
    assert (
        _save_dc(
            dragon,
            0,
            caster_abilities={},
            caster_proficiency_bonus=2,
            spellcasting_ability="cha",
        )
        == 20
    )
    # No resolvable spellcasting ability: falls back to the old flat
    # approximation, byte-for-byte (unaffected by this task).
    flat = _monster(attack_bonus=4)
    assert (
        _save_dc(
            flat,
            0,
            caster_abilities={},
            caster_proficiency_bonus=2,
            spellcasting_ability=None,
        )
        == 8 + 4
    )


def test_passive_damage_modifiers_passed_through():
    c = _caster()
    payload = {c.entity_id: {"resistances": ["fire"], "immunities": ["poison"]}}
    ctx = _build(c, [c], passive_damage_modifiers=payload)
    mods = ctx.passive_damage_modifiers[c.entity_id]
    assert "fire" in mods["resistances"]
    assert "poison" in mods["immunities"]


def test_passive_weapon_damage_bonus_reshaped_into_typed_field():
    """C02-S01: a weapon-tagged ``damage.bonus`` change folds into
    ``passive_damage_modifiers[id]["passive_weapon_damage_bonus"]``
    (``orchestrator._fold_active_effect_changes``); the builder must lift it
    into its own typed sidecar, mirroring ``passive_melee_damage_bonus``.
    """
    c = _caster()
    payload = {c.entity_id: {"passive_weapon_damage_bonus": "+3"}}
    ctx = _build(c, [c], passive_damage_modifiers=payload)
    assert ctx.passive_weapon_damage_bonus[c.entity_id] == "+3"


def test_save_sidecar_reshaped_into_typed_fields():
    target = _monster()
    save_modifiers = {
        target.entity_id: {
            "saves": {"dex": 1, "wis": -1},
            "passive_save_bonus": "+1d4",
            "passive_save_adv": ["WIS"],
            "passive_save_dis": ["STR"],
            "passive_save_auto_fail": ["DEX"],
        }
    }
    caster = _caster()
    ctx = _build(caster, [target], save_modifiers=save_modifiers)
    assert ctx.passive_save_modifiers[target.entity_id] == {"dex": 1, "wis": -1}
    assert ctx.passive_save_bonus[target.entity_id] == "+1d4"
    assert ctx.passive_save_adv[target.entity_id] == ["WIS"]
    assert ctx.passive_save_dis[target.entity_id] == ["STR"]
    assert ctx.passive_save_auto_fail[target.entity_id] == ["DEX"]


def test_roll_save_applies_bonus_and_short_circuits_auto_fail():
    """Regression for the dropped target-side save sidecar (cutover task 2).

    Would FAIL if the cutover silently dropped passive_save_bonus /
    passive_save_auto_fail: the typed save path must apply the bless-style bonus
    on a normal ability AND short-circuit the auto-fail ability to (0, False)
    without consuming a d20.
    """
    target = _caster(entity_id="char:cccccccccccc")
    save_modifiers = {
        target.entity_id: {
            "saves": {"wis": 2, "str": 0},
            "passive_save_bonus": "+1d4",  # bless-style
            "passive_save_auto_fail": ["STR"],  # e.g. paralyzed
        }
    }
    # Force the d20 so the bonus is the only stochastic-but-bounded contribution.
    ctx = _build(
        target,
        [target],
        save_modifiers=save_modifiers,
        rng=random.Random(7),
    )
    ctx.variables["force_save_d20"] = 10

    # Auto-fail ability (STR): short-circuits to (0, False), no d20, ignores DC.
    _roll = roll_save(ctx, target, "str", dc=1, target_index=0)
    total, succeeded = _roll.total, _roll.succeeded
    assert (total, succeeded) == (0, False)

    # Normal ability (WIS): natural 10 (forced) + wis mod 2 + bless 1d4 (1..4).
    _roll = roll_save(ctx, target, "wis", dc=5, target_index=0)
    total, succeeded = _roll.total, _roll.succeeded
    assert 13 <= total <= 16  # 10 + 2 + [1..4]
    assert succeeded is True


def test_roll_save_empty_sidecar_matches_plain_d20_plus_mod():
    # Default behavior (empty save sidecars) must be d20 + per-ability mod only,
    # so the golden corpus is unaffected.
    target = _caster(entity_id="char:dddddddddddd")
    save_modifiers = {target.entity_id: {"saves": {"dex": 3}}}
    ctx = _build(target, [target], save_modifiers=save_modifiers)
    ctx.variables["force_save_d20"] = 11
    _roll = roll_save(ctx, target, "dex", dc=14, target_index=0)
    total, succeeded = _roll.total, _roll.succeeded
    assert total == 11 + 3
    assert succeeded is True


def test_monster_spell_attack_bonus_uses_the_stat_block_spellcasting_ability():
    """C18 final review, finding 8: the bundled adult red dragon's
    Spellcasting reads "+12 to hit with spell attacks" (cha 23 -> +6, PB +6)
    while its Rend is +14 — a monster cast with a resolved
    ``spellcasting_ability`` overrides to-hit with PB + that modifier; the
    mundane path (``spellcasting_ability=None``) keeps ``attack_bonus``."""
    dragon = _monster(attack_bonus=14, charisma=23, proficiency_bonus_override=6)
    assert _build(dragon, [dragon], spellcasting_ability="cha").attack_bonus_override == 12
    assert _build(dragon, [dragon], spellcasting_ability=None).attack_bonus_override == 14
