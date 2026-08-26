"""F1 — per-actor D20-test modifier projection (SRD 5.2 "D20 Tests", "Proficiency").

Pure: reads a ``Combatant``, returns numbers. Foundry parity:
``module/documents/actor/actor.mjs`` (rollSavingThrow / rollSkill build
``@mod + @prof`` the same way); ``module/documents/actor/proficiency.mjs``.
"""

from __future__ import annotations

from dataclasses import dataclass

from dnd5e_engine.events import Ability
from dnd5e_engine.rules.dice import ability_modifier, proficiency_bonus
from dnd5e_engine.types.combat import Combatant

_SCORE_ATTR: dict[str, str] = {
    "str": "strength",
    "dex": "dexterity",
    "con": "constitution",
    "int": "intelligence",
    "wis": "wisdom",
    "cha": "charisma",
}


@dataclass(frozen=True)
class D20Modifier:
    ability: Ability
    ability_mod: int
    proficiency: int
    expertise: bool
    total: int


def ability_modifier_of(c: Combatant, ability: Ability) -> int:
    return ability_modifier(int(getattr(c, _SCORE_ATTR[ability])))


def proficiency_bonus_of(c: Combatant) -> int:
    if c.proficiency_bonus_override is not None:
        return c.proficiency_bonus_override
    return proficiency_bonus(c.character_level)


def save_modifier(c: Combatant, ability: Ability) -> D20Modifier:
    mod = ability_modifier_of(c, ability)
    prof = proficiency_bonus_of(c) if ability in c.save_proficiencies else 0
    return D20Modifier(ability, mod, prof, False, mod + prof)


def check_modifier(c: Combatant, ability: Ability, skill: str | None = None) -> D20Modifier:
    mod = ability_modifier_of(c, ability)
    prof = 0
    expertise = False
    if skill is not None and skill in c.skill_proficiencies:
        expertise = skill in c.skill_expertise
        prof = proficiency_bonus_of(c) * (2 if expertise else 1)
    return D20Modifier(ability, mod, prof, expertise, mod + prof)
