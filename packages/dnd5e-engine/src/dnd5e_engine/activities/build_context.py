"""Build an :class:`ActivityResolutionContext` from live combat state.

The integration crux of the Avrae→Foundry resolver cutover (Task 2 of
``docs/superpowers/plans/2026-06-03-bundled-asset-loader-cutover-plan.md``).

The new typed resolver consumes :class:`ActivityResolutionContext`. The OLD
Avrae path faked caster magnitudes off the narrow :class:`Combatant`
(``attack_bonus``, ``dexterity`` only — no per-ability scores, proficiency,
or spellcasting ability). This builder reproduces those approximations so the
scenario corpus stays green while the resolver swaps underneath:

* PC magnitudes mirror ``intent_resolver._spellcasting_mod`` /
  ``_proficiency_bonus`` / ``_spell_save_dc``: ``mod = max(0, attack_bonus-2)``,
  ``pb = 2``, ``save_dc = 8 + pb + mod``.
* Monster magnitudes mirror ``monster_ai._monster_save_dc``: ``mod =
  attack_bonus``, ``save_dc = 8 + attack_bonus``.

``caster_abilities`` is set uniformly across all six abilities to ``10 +
2*mod`` so the attack/damage handler — which resolves the governing ability
*dynamically* (explicit ``attack.ability`` → weapon SRD default → finesse
better-of-str/dex → spellcasting ability) — yields the old uniform ``@mod``
regardless of which ability it picks.

This module is PURE: no I/O, no orchestrator import, no double-compute. The
orchestrator already builds the per-entity passive sidecars (its
``_build_hydration_payload`` projection) and passes the two dicts this builder
needs — ``passive_damage_modifiers`` and ``save_modifiers`` — in as parameters at
the Task 5/6 cutover. This builder only RESHAPES them into the typed context:

* ``save_modifiers[id]["saves"]`` → ``passive_save_modifiers[id]`` ({ability:int})
* ``save_modifiers[id]["passive_save_bonus"]`` (signed dice string) → carried verbatim
* ``save_modifiers[id]["passive_save_adv"/"_dis"/"_auto_fail"]`` (UPPER-case
  ability-code lists) → carried verbatim

so the typed save path (``save_primitive.roll_save``) consumes the SAME bless/bane
bonus, advantage/disadvantage, and auto-fail the OLD Avrae ``effects/save.py``
path did. Empty / absent sidecar fields reproduce the prior behavior exactly.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from dnd5e_engine.activities.context import ActivityResolutionContext
from dnd5e_engine.events import CombatEvent
from dnd5e_engine.rules.dice import proficiency_bonus
from dnd5e_engine.types.combat import Combatant

if TYPE_CHECKING:
    from dnd5e_srd_data.schema.common import PassiveEffect
    from dnd5e_srd_data.schema.spell import Spell

_ABILITIES = ("str", "dex", "con", "int", "wis", "cha")


def _caster_mod(caster: Combatant) -> int:
    """The OLD uniform caster modifier, branching on entity type.

    Monster: ``attack_bonus`` (``monster_ai``). PC: ``max(0, attack_bonus-2)``
    (``intent_resolver._spellcasting_mod``).
    """
    if caster.entity_type == "Monster":
        return caster.attack_bonus
    return max(0, caster.attack_bonus - 2)


def _save_dc(caster: Combatant, mod: int) -> int:
    """Reproduce the OLD flat save DC for the standalone-cast / monster path.

    Monster: ``8 + attack_bonus`` (``_monster_save_dc``). PC: ``8 + pb + mod``
    with ``pb = 2`` (``_spell_save_dc``).
    """
    if caster.entity_type == "Monster":
        return 8 + caster.attack_bonus
    return 8 + 2 + mod


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
    scale_values: dict[str, int | str] | None = None,
    class_levels: dict[str, int] | None = None,
    is_feature_invocation: bool = False,
) -> ActivityResolutionContext:
    """Adapt the caster + the pre-computed hydration sidecars into the typed
    :class:`ActivityResolutionContext` the new resolver consumes.

    Caster magnitudes reproduce the OLD Avrae approximations (see module
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

    ``is_feature_invocation`` distinguishes a USE_FEATURE context from a spell /
    item cast. The blanket ``save_dc_override`` reproduces the Avrae-era flat
    SPELL DC (``8 + PB + caster_mod``); applying it to a FEATURE save activity is
    wrong — a feature must compute its own DC from its save's ability + PB. So
    for a feature invocation the override is omitted (``None``), letting the save
    resolver fall through to ``save.dc.calculation``. The spell / item path keeps
    the blanket override unchanged (the full spellcasting-ability/DC seam stays
    deferred).
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
        # Monsters/NPCs have no per-ability sheet here: keep the Avrae-era
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
    for entity_id, dmg_entry in passive_damage_modifiers.items():
        # ``passive_damage_modifiers`` is a WIDE dict: resistance/immunity/
        # vulnerability lists PLUS the signed-dice ``passive_to_hit_bonus`` STRING
        # the orchestrator projection wedges in (mirrors the OLD Avrae sidecar).
        to_hit: object = dmg_entry.get("passive_to_hit_bonus")
        if isinstance(to_hit, str) and to_hit:
            passive_attack_bonus[entity_id] = to_hit
        melee_dmg: object = dmg_entry.get("passive_melee_damage_bonus")
        if isinstance(melee_dmg, str) and melee_dmg:
            passive_melee_damage_bonus[entity_id] = melee_dmg
    passive_save_adv: dict[str, list[str]] = {}
    passive_save_dis: dict[str, list[str]] = {}
    passive_save_auto_fail: dict[str, list[str]] = {}
    for entity_id, entry in save_modifiers.items():
        saves = entry.get("saves")
        if isinstance(saves, dict):
            passive_save_modifiers[entity_id] = {a: int(v) for a, v in saves.items()}
        bonus = entry.get("passive_save_bonus")
        if isinstance(bonus, str) and bonus:
            passive_save_bonus[entity_id] = bonus
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
        save_dc_override=None if is_feature_invocation else _save_dc(caster, mod),
        attack_bonus_override=caster.attack_bonus,
        passive_damage_modifiers=passive_damage_modifiers,
        passive_save_modifiers=passive_save_modifiers,
        passive_save_bonus=passive_save_bonus,
        passive_attack_bonus=passive_attack_bonus,
        passive_melee_damage_bonus=passive_melee_damage_bonus,
        passive_save_adv=passive_save_adv,
        passive_save_dis=passive_save_dis,
        passive_save_auto_fail=passive_save_auto_fail,
        check_modifiers={},
        source_passive_effects=source_passive_effects,
        spell_book=spell_book,
        scale_values=scale_values or {},
        class_levels=class_levels or {},
    )
