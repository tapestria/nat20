"""Pure resolution of a CharacterBuildSpec into a complete PartyMemberSpec.

Character values (abilities, HP, AC, speed, proficiencies, senses, resistances, …)
come from ``derive_sheet``; combat-instance values (identity, and anything the host
pinned on ``CombatInstance``) override it. See ``build_party_member``.
"""

from __future__ import annotations

from dnd5e_srd_data.loader import AssetLoader

from dnd5e_engine.build_spec import CharacterBuildSpec, CombatInstance, derive_sheet
from dnd5e_engine.specs import PartyMemberSpec


def build_party_member(
    build_spec: CharacterBuildSpec, instance: CombatInstance, *, loader: AssetLoader
) -> PartyMemberSpec:
    """Resolve a build spec plus a combat instance into a ``PartyMemberSpec``.

    Every character value comes from ``derive_sheet`` unless the host pinned
    it on ``instance``: ``hp_max`` / ``hp_current`` / ``ac`` / ``attack_bonus``
    / ``base_speed`` whenever they are not ``None`` (decided by an ordinary
    ``is None`` check, so a ``CombatInstance`` rebuilt from
    ``CombatInstance(**inst.model_dump())`` still derives whatever it left
    unset). An unpinned ``attack_bonus`` stays unset on the built spec, so
    the engine computes each weapon's to-hit bonus. Raises ``ValueError`` for
    an invalid build (see ``derive_sheet``).
    """
    sheet = derive_sheet(build_spec, loader=loader)
    hp_max = sheet.hp_max if instance.hp_max is None else instance.hp_max
    scores = sheet.ability_scores
    member = PartyMemberSpec(
        entity_id=instance.entity_id,
        name=instance.name,
        initiative=instance.initiative,
        hp_current=hp_max if instance.hp_current is None else instance.hp_current,
        hp_max=hp_max,
        ac=sheet.ac if instance.ac is None else instance.ac,
        strength=scores.strength,
        dexterity=scores.dexterity,
        constitution=scores.constitution,
        intelligence=scores.intelligence,
        wisdom=scores.wisdom,
        charisma=scores.charisma,
        zone_id=instance.zone_id,
        spell_slots=dict(instance.spell_slots) or dict(sheet.spell_slots),
        pact_slots=dict(instance.pact_slots) or dict(sheet.pact_slots),
        spells_known=list(instance.spells_known),
        concentration_effect_id=instance.concentration_effect_id,
        character_level=build_spec.level,
        class_slug=build_spec.class_slug,
        classes=dict(build_spec.classes),
        subclass_slug=build_spec.subclass_slug,
        species_slug=build_spec.species_slug,
        base_speed=sheet.base_speed if instance.base_speed is None else instance.base_speed,
        equipment=build_spec.equipment,
        damage_resistances=list(sheet.damage_resistances),
        damage_immunities=list(sheet.damage_immunities),
        condition_immunities=list(sheet.condition_immunities),
        senses=sheet.senses,
        movement_modes=sheet.movement_modes,
        save_proficiencies=tuple(sorted(sheet.save_proficiencies)),
        skill_proficiencies=tuple(sorted(sheet.skill_proficiencies)),
        skill_expertise=tuple(sorted(sheet.skill_expertise)),
        weapon_proficiencies=tuple(sorted(sheet.weapon_proficiencies)),
    )
    if instance.attack_bonus is not None:
        # model_copy marks the field as set (pydantic 2.13), which keeps the C15
        # sentinel reading it as the host's verbatim to-hit bonus.
        member = member.model_copy(update={"attack_bonus": instance.attack_bonus})
    return member


__all__ = [
    "build_party_member",
]
