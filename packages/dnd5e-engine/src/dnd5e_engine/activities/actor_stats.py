"""F1 — per-actor D20-test modifier projection (SRD 5.2 "D20 Tests", "Proficiency").

Pure: reads a ``Combatant``, returns numbers. Foundry parity:
``module/documents/actor/actor.mjs`` (rollSavingThrow / rollSkill build
``@mod + @prof`` the same way); ``module/documents/actor/proficiency.mjs``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from dnd5e_engine.events import Ability
from dnd5e_engine.rules.dice import ability_modifier, proficiency_bonus
from dnd5e_engine.rules.skills import SKILL_ABILITIES
from dnd5e_engine.types.combat import Combatant

# SRD 5.2 §Ability Scores — the closed six-ability set, in canonical order.
ABILITY_CODES: Final[tuple[Ability, ...]] = ("str", "dex", "con", "int", "wis", "cha")

_SCORE_ATTR: Final[dict[Ability, str]] = {
    "str": "strength",
    "dex": "dexterity",
    "con": "constitution",
    "int": "intelligence",
    "wis": "wisdom",
    "cha": "charisma",
}

# Inverse of ``_SCORE_ATTR`` — the long ability NAME (``"wisdom"``) the SRD skill
# table in ``rules/skills.py`` uses, back to the closed ``Ability`` code the
# engine's typed surfaces carry.
_ABILITY_BY_NAME: Final[dict[str, Ability]] = {name: code for code, name in _SCORE_ATTR.items()}


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


def skill_ability(skill: str) -> Ability | None:
    """The governing ability code for a long-form skill slug, or ``None``.

    SRD 5.2 §Skills — the skill→ability table is ``rules/skills.SKILL_ABILITIES``
    (the engine's single source for it); this only translates its long ability
    NAME into the closed ``Ability`` code. Returns ``None`` for a slug that is
    not an SRD skill (e.g. a Foundry 3-letter code or a tool proficiency), so
    callers can skip it rather than guess a governing ability.
    """
    name = SKILL_ABILITIES.get(skill)
    if name is None:
        return None
    return _ABILITY_BY_NAME.get(name)
