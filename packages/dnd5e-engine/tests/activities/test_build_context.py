"""Task 2 cutover — ``build_activity_context`` from live combat state.

Locks the magnitude-reproduction contract (field-mapping table in
``docs/superpowers/plans/2026-06-03-bundled-asset-loader-cutover-plan.md``):
the new typed resolver context must reproduce the OLD Avrae path's caster
magnitudes (``attack_bonus_override``, flat ``save_dc``, uniform ``@mod``
across all six abilities) and reuse the existing per-entity passive sidecars.
"""

from __future__ import annotations

import random

from dnd5e_engine.activities.build_context import build_activity_context
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
    assert ctx.save_dc_override == 8 + 5  # deferred spell-DC seam: untouched
    assert ctx.ability_mod("dex") == 2
    for ability in ("str", "con", "int", "wis", "cha"):
        assert ctx.ability_mod(ability) == 0


def test_pc_level5_pb_is_three():
    # PB scales with level (2 + (level-1)//4): +3 at level 5.
    caster = _caster(character_level=5)
    ctx = _build(caster, [caster])
    assert ctx.caster_proficiency_bonus == 3
    # The deferred spell-DC override path still uses the Avrae mod, untouched.
    assert ctx.save_dc_override == 8 + 2 + max(0, 5 - 2)


def test_monster_caster_magnitudes_uniform_mod_and_flat_dc():
    # Monster: mod = attack_bonus (monster_ai), save_dc = 8 + attack_bonus
    # (_monster_save_dc), uniform across all six abilities.
    caster = _monster(attack_bonus=4)
    ctx = _build(caster, [caster])
    assert ctx.attack_bonus_override == 4
    assert ctx.save_dc_override == 8 + 4
    for ability in ("str", "dex", "con", "int", "wis", "cha"):
        assert ctx.ability_mod(ability) == 4


def test_passive_damage_modifiers_passed_through():
    c = _caster()
    payload = {c.entity_id: {"resistances": ["fire"], "immunities": ["poison"]}}
    ctx = _build(c, [c], passive_damage_modifiers=payload)
    mods = ctx.passive_damage_modifiers[c.entity_id]
    assert "fire" in mods["resistances"]
    assert "poison" in mods["immunities"]


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
    total, succeeded = roll_save(ctx, target, "str", dc=1, target_index=0)
    assert (total, succeeded) == (0, False)

    # Normal ability (WIS): natural 10 (forced) + wis mod 2 + bless 1d4 (1..4).
    total, succeeded = roll_save(ctx, target, "wis", dc=5, target_index=0)
    assert 13 <= total <= 16  # 10 + 2 + [1..4]
    assert succeeded is True


def test_roll_save_empty_sidecar_matches_plain_d20_plus_mod():
    # Default behavior (empty save sidecars) must be d20 + per-ability mod only,
    # so the golden corpus is unaffected.
    target = _caster(entity_id="char:dddddddddddd")
    save_modifiers = {target.entity_id: {"saves": {"dex": 3}}}
    ctx = _build(target, [target], save_modifiers=save_modifiers)
    ctx.variables["force_save_d20"] = 11
    total, succeeded = roll_save(ctx, target, "dex", dc=14, target_index=0)
    assert total == 11 + 3
    assert succeeded is True
