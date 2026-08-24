"""Character-sheet derivation: a build-spec + loader → a combat-ready PartyMemberSpec.

``derive_sheet`` computes the values ``CharacterBuildSpec`` doesn't carry
(HP/AC/attack bonus/spell slots) from SRD 5.2 formulas and the canonical
class/armor/spell data, then delegates final assembly to
``dnd5e_engine.build_party_member`` — which already folds ``CombatInstance``'s
``spell_slots``/``spells_known`` straight into the returned ``PartyMemberSpec``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dnd5e_engine import CombatInstance, build_party_member

from nat20_bridge.slots import slots_for

if TYPE_CHECKING:
    from dnd5e_engine import CharacterBuildSpec, PartyMemberSpec
    from dnd5e_srd_data.loader import AssetLoader

# Class.hit_die is a HitDie StrEnum ("d6"/"d8"/"d10"/"d12"); this maps the
# literal die string to its max face value.
_DIE_MAX = {"d6": 6, "d8": 8, "d10": 10, "d12": 12}


def _ability_mod(score: int) -> int:
    return (score - 10) // 2


def _compute_ac(spec: CharacterBuildSpec, loader: AssetLoader, dex_mod: int) -> int:
    body_ac: int | None = None
    shield_bonus = 0
    for slug in spec.equipment:
        armor = loader.get_armor(slug)
        if armor is None:
            continue
        if armor.armor_category == "shield":
            shield_bonus += 2 + armor.magical_bonus
            continue
        if armor.dex_bonus_max is not None:
            body_ac = armor.base_ac + min(dex_mod, armor.dex_bonus_max) + armor.magical_bonus
        else:
            body_ac = armor.base_ac + dex_mod + armor.magical_bonus
    if body_ac is None:
        return 10 + dex_mod + shield_bonus
    return body_ac + shield_bonus


def derive_sheet(
    spec: CharacterBuildSpec,
    *,
    name: str,
    entity_id: str,
    loader: AssetLoader,
    hp_current: int | None = None,
    spells_known: list[str] | None = None,
    zone_id: str = "0,0",
    initiative: int = 0,
) -> PartyMemberSpec:
    cls = loader.get_class(spec.class_slug)
    if cls is None:
        raise ValueError(f"unknown class: {spec.class_slug!r}")

    ab = spec.ability_scores
    con_mod = _ability_mod(ab.constitution)
    str_mod = _ability_mod(ab.strength)
    dex_mod = _ability_mod(ab.dexterity)

    level = spec.level
    die_max = _DIE_MAX[str(cls.hit_die)]
    per_level_gain = max(die_max // 2 + 1 + con_mod, 1)
    hp_max = die_max + con_mod + (level - 1) * per_level_gain
    hp_max = max(hp_max, level)

    ac = _compute_ac(spec, loader, dex_mod)

    proficiency = 2 + (level - 1) // 4
    attack_bonus = proficiency + str_mod

    slots = slots_for(str(cls.spellcasting.progression), level)

    known = list(spells_known or [])
    for slug in known:
        if loader.get_spell(slug) is None:
            raise ValueError(f"unknown spell: {slug!r}")

    resolved_hp_current = hp_current if hp_current is not None else hp_max

    instance = CombatInstance(
        entity_id=entity_id,
        name=name,
        hp_current=resolved_hp_current,
        hp_max=hp_max,
        ac=ac,
        attack_bonus=attack_bonus,
        initiative=initiative,
        zone_id=zone_id,
        spell_slots=slots,
        spells_known=tuple(known),
    )
    return build_party_member(spec, instance, loader=loader)


__all__ = ["derive_sheet"]
