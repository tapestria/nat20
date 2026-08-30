"""Build an ``ActivityResolutionContext`` from live combat state.

This is the bridge between the orchestrator's mutable ``_LiveCombat`` and the
pure activity resolvers. It reads the caster's real six ability scores,
level-derived proficiency bonus, spellcasting ability and ``@scale`` values,
folds in the passive attack/damage/save/check modifiers projected from active
effects and conditions, and hands the resolvers a single immutable context.

The resolvers never touch live combat state directly — everything they need
arrives on the context, which is what keeps them pure and testable.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

from dnd5e_engine.activities.context import ActivityResolutionContext
from dnd5e_engine.activities.dice import roll_expr
from dnd5e_engine.events import CombatEvent
from dnd5e_engine.rules.conditions import active_condition_names
from dnd5e_engine.rules.dice import proficiency_bonus
from dnd5e_engine.types.combat import Combatant

if TYPE_CHECKING:
    from dnd5e_srd_data.schema.common import PassiveEffect
    from dnd5e_srd_data.schema.spell import Spell

    from dnd5e_engine.types.effects import ActiveEffect

_ABILITIES = ("str", "dex", "con", "int", "wis", "cha")


def _caster_mod(caster: Combatant) -> int:
    """The OLD uniform caster modifier, branching on entity type.

    Monster: ``attack_bonus`` (``monster_ai``). PC: ``max(0, attack_bonus-2)``
    (``intent_resolver._spellcasting_mod``).
    """
    if caster.entity_type == "Monster":
        return caster.attack_bonus
    return max(0, caster.attack_bonus - 2)


def _save_dc(
    caster: Combatant,
    mod: int,
    *,
    caster_abilities: dict[str, int],
    caster_proficiency_bonus: int,
    spellcasting_ability: str | None,
) -> int:
    """SRD 5.2 §Spellcasting, Spell Save DC: ``8 + proficiency bonus + your
    spellcasting ability modifier`` — verified against
    ``raw_sources/foundry/packs/_source/content24/appendices/appendix-d-rule-
    references.yml`` (journal page 8DajfNll90eeKcmB, "Saving Throws").

    A Character caster with a resolved ``spellcasting_ability`` (the real
    class -> ability mapping, e.g. cleric -> wis) uses the honest formula
    against its real ability scores + proficiency bonus (both already
    computed for real above). Monster path AND a Character with no resolvable
    spellcasting ability (unknown class / a non-caster class / a non-cast_spell
    intent such as ``use_item``, which never sets ``spellcasting_ability``)
    fall back to the OLD flat approximation byte-for-byte: Monster
    ``8 + attack_bonus`` (``_monster_save_dc``); PC ``8 + 2 + mod`` (the
    the legacy evaluator-era ``_spell_save_dc``, ``pb`` hardcoded to ``2``).
    """
    if caster.entity_type == "Monster":
        return 8 + caster.attack_bonus
    if spellcasting_ability:
        ability_mod = (caster_abilities.get(spellcasting_ability, 10) - 10) // 2
        return 8 + caster_proficiency_bonus + ability_mod
    return 8 + 2 + mod


def _spell_dc_bonus(
    caster: Combatant,
    passive_damage_modifiers: dict[str, dict[str, Any]],
    rng: random.Random,
) -> int:
    """Fold the Foundry ``system.bonuses.spell.dc`` active-effect bucket (a
    flat/dice bonus to the CASTER's own spell save DC — e.g. a Rod of the Pact
    Keeper) into the save-DC override. Folded by the orchestrator's
    ``_fold_active_effect_changes`` into ``passive_damage_modifiers[caster_id]
    ["passive_spell_dc_bonus"]`` as a signed numeric/dice string; rolled here
    (through the seeded rng, consistent with the sibling to-hit/damage sidecar
    rolls) and added on top of the real spellcasting-ability DC. Absent
    caster/bonus -> +0 (empty dict keeps the golden corpus identical).
    """
    entry = passive_damage_modifiers.get(caster.entity_id, {})
    bonus_expr = entry.get("passive_spell_dc_bonus")
    if isinstance(bonus_expr, str) and bonus_expr:
        return roll_expr(bonus_expr, rng)
    return 0


def _check_modifier_sidecar(
    check_modifiers: dict[str, dict[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    """Narrow the WIDE hydration ``check_modifiers[id]`` entry to the typed
    per-actor check sidecar ``activities/check.py`` consumes.

    The orchestrator entry carries the condition-derived adv/dis LISTS
    (``passive_check_adv`` / ``passive_check_dis``) alongside the F1d projection;
    only ``ability_mods`` (all six abilities), ``skills`` (each proficient skill,
    proficiency/Expertise already folded in) and the resolved ``disadvantage``
    boolean cross into the context. Absent (``None``) → empty, leaving the golden
    corpus identical (no actor projection ⇒ every check modifier is +0).
    """
    out: dict[str, dict[str, Any]] = {}
    for entity_id, entry in (check_modifiers or {}).items():
        ability_mods = entry.get("ability_mods")
        skills = entry.get("skills")
        out[entity_id] = {
            "ability_mods": (
                {a: int(v) for a, v in ability_mods.items()}
                if isinstance(ability_mods, dict)
                else {}
            ),
            "skills": ({s: int(v) for s, v in skills.items()} if isinstance(skills, dict) else {}),
            "disadvantage": bool(entry.get("disadvantage", False)),
        }
    return out


def build_activity_context(
    caster: Combatant,
    targets: list[Combatant],
    *,
    rng: random.Random,
    event_emitter: Callable[[CombatEvent], None],
    slot_level: int | None,
    base_spell_level: int | None,
    spellcasting_ability: str | None,
    concentration: bool,
    source_passive_effects: list[PassiveEffect],
    spell_book: dict[str, Spell],
    passive_damage_modifiers: dict[str, dict[str, list[str]]],
    save_modifiers: dict[str, dict[str, Any]],
    check_modifiers: dict[str, dict[str, Any]] | None = None,
    target_cover: dict[str, str] | None = None,
    target_distance_ft: dict[str, int] | None = None,
    attacker_grappler_id: str | None = None,
    d20_test_penalty: dict[str, int] | None = None,
    scale_values: dict[str, int | str] | None = None,
    class_levels: dict[str, int] | None = None,
    cast_level_override: int | None = None,
    is_feature_invocation: bool = False,
    active_effects: Sequence[ActiveEffect] = (),
    sneak_attack_spent: dict[str, bool] | None = None,
    sneak_attack_ally_adjacent: dict[str, bool] | None = None,
    target_unseen: dict[str, bool] | None = None,
    attacker_unseen_by: dict[str, bool] | None = None,
) -> ActivityResolutionContext:
    """Adapt the caster + the pre-computed hydration sidecars into the typed
    ``ActivityResolutionContext`` the new resolver consumes.

    Caster magnitudes reproduce the OLD the legacy evaluator approximations (see module
    docstring). ``passive_damage_modifiers`` and ``save_modifiers`` are the two
    dicts the orchestrator's ``_build_hydration_payload`` already produces —
    passed IN so this builder stays pure (no orchestrator import, no I/O, no
    double-compute). The wide per-target ``save_modifiers[id]`` entry is reshaped
    into the four typed save-sidecar fields; absent fields default empty, leaving
    the golden corpus identical.

    ``scale_values`` / ``class_levels`` are the PRE-RESOLVED ``@scale.*`` /
    ``@classes.<class>.levels`` carriers. They are resolved by the orchestrator /
    build-party seam (loader access there — ``activities/scale.build_scale_values``)
    and passed IN as plain data; this pure builder never touches a loader. Absent
    (``None``) → empty, leaving the golden corpus identical.

    ``target_cover`` is the PRE-RESOLVED per-target SRD 5.2 §Cover degree
    (``"none"``/``"half"``/``"three_quarters"``/``"total"``), computed by the
    orchestrator (``_target_cover_map``, spatial-seam access there) from the
    caster's and each target's live zone via ``topology.cover_between``. This
    pure builder never touches the spatial seam; absent (``None``) → empty,
    leaving the golden corpus identical (no cover geometry ⇒ no bonus).

    ``is_feature_invocation`` distinguishes a USE_FEATURE context from a spell /
    item cast. The blanket ``save_dc_override`` carries the real spell save DC
    (``_save_dc``: ``8 + PB + spellcasting-ability mod``, class→ability from
    canonical class data, with the documented flat fallback for unknown /
    non-caster classes and item casts); applying it to a FEATURE save activity
    is wrong — a feature must compute its own DC from its save's ability + PB.
    So for a feature invocation the override is omitted (``None``), letting the
    save resolver fall through to ``save.dc.calculation``. The spell / item
    path keeps the blanket override.

    ``cast_level_override`` passes straight through to
    ``ActivityResolutionContext`` — a ``use_item`` charges_to_spend
    upcast's forced delegated-cast level (orchestrator-computed off the
    charge gate's own cost accounting). ``None`` (the default) leaves
    ``resolve_cast`` (``activities/cast.py``) to fall back to the wrapper
    activity's own/base spell level, unchanged from before this field
    existed.
    """
    mod = _caster_mod(caster)
    if caster.entity_type == "Character":
        # PCs carry real six-ability scores + character_level (piece 3), so the
        # `@mod`/`@prof`/`@abilities.<ab>.mod` tokens resolve to honest values.
        caster_abilities = {
            "str": caster.strength,
            "dex": caster.dexterity,
            "con": caster.constitution,
            "int": caster.intelligence,
            "wis": caster.wisdom,
            "cha": caster.charisma,
        }
        caster_proficiency_bonus = proficiency_bonus(caster.character_level)
    else:
        # Monsters/NPCs have no per-ability sheet here: keep the legacy evaluator-era
        # uniform fake (10 + 2*mod across all six abilities, PB 2) so the
        # dynamic governing-ability resolution in attack.py reproduces the old
        # uniform @mod for any ability it picks.
        caster_abilities = {ability: 10 + 2 * mod for ability in _ABILITIES}
        caster_proficiency_bonus = 2

    # Hydration's ``save_modifiers[id]`` is a WIDE dict: a ``saves`` sub-dict
    # ({ability:int}) plus the per-target sidecar keys (passive_save_bonus dice
    # string, passive_save_adv / _dis / _auto_fail UPPER-case ability lists).
    # Project EACH into its typed context field so the typed save path consumes
    # the full sidecar the OLD effects/save.py path did.
    passive_save_modifiers: dict[str, dict[str, int]] = {}
    passive_save_bonus: dict[str, str] = {}
    # Per-attacker to-hit dice bonus (Bless +1d4 / Bane −1d4). The orchestrator
    # projection lands it on ``passive_damage_modifiers[id]["passive_to_hit_bonus"]``
    # (a signed dice string); lift it into its own typed sidecar so attack.py can
    # roll it without reaching into the resistance-shaped damage dict.
    passive_attack_bonus: dict[str, str] = {}
    # Per-attacker MELEE-WEAPON damage bonus (Rage +2). The orchestrator fold
    # lands it on ``passive_damage_modifiers[id]["passive_melee_damage_bonus"]``
    # (a signed numeric/dice string); lift it into its own typed sidecar so
    # attack.py adds it to a melee weapon swing only.
    passive_melee_damage_bonus: dict[str, str] = {}
    # Per-attacker WEAPON-ONLY damage bonus (a +N weapon / weapon-tagged
    # ``damage.bonus`` change). The orchestrator fold lands it on
    # ``passive_damage_modifiers[id]["passive_weapon_damage_bonus"]`` (a
    # signed numeric/dice string, action-type-tagged so it does not leak into
    # spell attacks); lift it into its own typed sidecar so attack.py can add
    # it to any weapon swing (melee or ranged), symmetric with
    # ``passive_melee_damage_bonus``.
    passive_weapon_damage_bonus: dict[str, str] = {}
    # Foundry ``system.bonuses.rwak.damage`` (a ranged-weapon-attack damage
    # bonus — the ranged analog of Rage's melee-only ``mwak`` bonus) /
    # ``system.bonuses.{msak,rsak}.damage`` (melee / ranged SPELL-attack
    # damage bonuses). Symmetric with ``passive_melee_damage_bonus`` above;
    # consumed in ``attack.py`` gated on the swing's own melee/ranged +
    # weapon/spell shape.
    passive_ranged_damage_bonus: dict[str, str] = {}
    passive_melee_spell_damage_bonus: dict[str, str] = {}
    passive_ranged_spell_damage_bonus: dict[str, str] = {}
    for entity_id, dmg_entry in passive_damage_modifiers.items():
        # ``passive_damage_modifiers`` is a WIDE dict: resistance/immunity/
        # vulnerability lists PLUS the signed-dice ``passive_to_hit_bonus`` STRING
        # the orchestrator projection wedges in (mirrors the OLD the legacy evaluator sidecar).
        to_hit: object = dmg_entry.get("passive_to_hit_bonus")
        if isinstance(to_hit, str) and to_hit:
            passive_attack_bonus[entity_id] = to_hit
        melee_dmg: object = dmg_entry.get("passive_melee_damage_bonus")
        if isinstance(melee_dmg, str) and melee_dmg:
            passive_melee_damage_bonus[entity_id] = melee_dmg
        weapon_dmg: object = dmg_entry.get("passive_weapon_damage_bonus")
        if isinstance(weapon_dmg, str) and weapon_dmg:
            passive_weapon_damage_bonus[entity_id] = weapon_dmg
        ranged_dmg: object = dmg_entry.get("passive_ranged_damage_bonus")
        if isinstance(ranged_dmg, str) and ranged_dmg:
            passive_ranged_damage_bonus[entity_id] = ranged_dmg
        melee_spell_dmg: object = dmg_entry.get("passive_melee_spell_damage_bonus")
        if isinstance(melee_spell_dmg, str) and melee_spell_dmg:
            passive_melee_spell_damage_bonus[entity_id] = melee_spell_dmg
        ranged_spell_dmg: object = dmg_entry.get("passive_ranged_spell_damage_bonus")
        if isinstance(ranged_spell_dmg, str) and ranged_spell_dmg:
            passive_ranged_spell_damage_bonus[entity_id] = ranged_spell_dmg
    passive_save_adv: dict[str, list[str]] = {}
    passive_save_dis: dict[str, list[str]] = {}
    passive_save_auto_fail: dict[str, list[str]] = {}
    # Per-target flat AC bonus (Shield's +5). The orchestrator fold lands it on
    # ``save_modifiers[id]["passive_ac_bonus"]`` as a signed numeric/dice
    # STRING (mirroring the other passive_* sidecar keys on this same wide
    # dict); resolve it to a concrete int here via the same seeded ``roll_expr``
    # every other sidecar bonus uses (a plain literal like Shield's "5" draws
    # no dice, so this never perturbs the seed stream for the one reaction
    # this cluster needs it for).
    passive_ac_bonus: dict[str, int] = {}
    for entity_id, entry in save_modifiers.items():
        saves = entry.get("saves")
        if isinstance(saves, dict):
            passive_save_modifiers[entity_id] = {a: int(v) for a, v in saves.items()}
        bonus = entry.get("passive_save_bonus")
        if isinstance(bonus, str) and bonus:
            passive_save_bonus[entity_id] = bonus
        ac_bonus = entry.get("passive_ac_bonus")
        if isinstance(ac_bonus, str) and ac_bonus:
            passive_ac_bonus[entity_id] = roll_expr(ac_bonus, rng)
        for src_key, dest in (
            ("passive_save_adv", passive_save_adv),
            ("passive_save_dis", passive_save_dis),
            ("passive_save_auto_fail", passive_save_auto_fail),
        ):
            codes = entry.get(src_key)
            if isinstance(codes, list) and codes:
                dest[entity_id] = [str(c) for c in codes]

    return ActivityResolutionContext(
        rng=rng,
        caster=caster,
        targets=targets,
        event_emitter=event_emitter,
        caster_abilities=caster_abilities,
        caster_proficiency_bonus=caster_proficiency_bonus,
        caster_level=caster.character_level,
        spellcasting_ability=spellcasting_ability,
        is_proficient_attack=True,
        concentration=concentration,
        slot_level=slot_level,
        base_spell_level=base_spell_level,
        save_dc_override=(
            None
            if is_feature_invocation
            else _save_dc(
                caster,
                mod,
                caster_abilities=caster_abilities,
                caster_proficiency_bonus=caster_proficiency_bonus,
                spellcasting_ability=spellcasting_ability,
            )
            + _spell_dc_bonus(caster, passive_damage_modifiers, rng)
        ),
        attack_bonus_override=caster.attack_bonus,
        passive_damage_modifiers=passive_damage_modifiers,
        passive_save_modifiers=passive_save_modifiers,
        passive_save_bonus=passive_save_bonus,
        passive_attack_bonus=passive_attack_bonus,
        passive_melee_damage_bonus=passive_melee_damage_bonus,
        passive_weapon_damage_bonus=passive_weapon_damage_bonus,
        passive_ranged_damage_bonus=passive_ranged_damage_bonus,
        passive_melee_spell_damage_bonus=passive_melee_spell_damage_bonus,
        passive_ranged_spell_damage_bonus=passive_ranged_spell_damage_bonus,
        passive_save_adv=passive_save_adv,
        passive_save_dis=passive_save_dis,
        passive_save_auto_fail=passive_save_auto_fail,
        passive_ac_bonus=passive_ac_bonus,
        target_cover=target_cover or {},
        # C16b — SRD 5.2 "Unseen Attackers and Targets": the two PRE-RESOLVED
        # per-target visibility maps, computed by the orchestrator
        # (``_target_visibility_maps``, spatial-seam access there). This pure
        # builder never touches the spatial seam; absent (``None``) → empty,
        # leaving the golden corpus identical (no lighting ⇒ everyone seen).
        target_unseen=target_unseen or {},
        attacker_unseen_by=attacker_unseen_by or {},
        target_distance_ft=target_distance_ft or {},
        attacker_grappler_id=attacker_grappler_id,
        d20_test_penalty=d20_test_penalty or {},
        # SRD §Advantage / §Sneak Attack — the caster's own active effects
        # (attacker-side ``flags.advantage.attack`` / ``flags.disadvantage.attack``
        # read by ``attack.py``) plus the two Sneak Attack sidecars. The
        # orchestrator projects these from live state; empty defaults keep the
        # golden corpus identical (no advantage producer, no rider).
        active_effects=active_effects,
        # F2b — condition-derived advantage sidecars (SRD §Advantage and
        # Disadvantage). Projected straight off the live ``Combatant.conditions``
        # so the pure resolver never touches combat state; no conditions ⇒ empty
        # ⇒ ``normal``, byte-identical to the pre-F2b seeded stream.
        attacker_conditions=active_condition_names(caster.conditions),
        target_conditions={t.entity_id: active_condition_names(t.conditions) for t in targets},
        sneak_attack_spent=sneak_attack_spent or {},
        sneak_attack_ally_adjacent=sneak_attack_ally_adjacent or {},
        check_modifiers=_check_modifier_sidecar(check_modifiers),
        source_passive_effects=source_passive_effects,
        spell_book=spell_book,
        scale_values=scale_values or {},
        class_levels=class_levels or {},
        cast_level_override=cast_level_override,
    )
