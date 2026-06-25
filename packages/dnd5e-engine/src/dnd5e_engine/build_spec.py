"""The build-spec contract: the typed input that resolves into a complete PC.

A 7c test/seed factory produces these now; the char-creation build-core (CharacterDraft,
spec-only today) becomes a second producer of the identical contract later. Resolution
(build_party_member) is pure; selection (who fills the build-spec) is the producer's job.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

# Long-form -> the canonical field; short-form aliases the backend cache / lib may pass.
_ABILITY_ALIASES = {
    "str": "strength",
    "dex": "dexterity",
    "con": "constitution",
    "int": "intelligence",
    "wis": "wisdom",
    "cha": "charisma",
}
_LONG = set(_ABILITY_ALIASES.values())


class AbilityScores(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    strength: int = 10
    dexterity: int = 10
    constitution: int = 10
    intelligence: int = 10
    wisdom: int = 10
    charisma: int = 10


class CharacterBuildSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    species_slug: str
    class_slug: str
    subclass_slug: str | None = None
    level: int = Field(ge=1, le=20, default=1)
    ability_scores: AbilityScores = Field(default_factory=AbilityScores)
    equipment: tuple[str, ...] = ()
    selected_choices: tuple[str, ...] = ()


class CombatInstance(BaseModel):
    """Combat-instance values that are NOT character-derived.

    Entity identity (entity_id/name) + rolled/looked-up combat stats.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    entity_id: str
    name: str
    hp_current: int
    hp_max: int
    ac: int = 10
    attack_bonus: int = 0
    initiative: int = 0
    zone_id: str = ""
    concentration_effect_id: str | None = None
    spell_slots: dict[int, int] = Field(default_factory=dict)
    spells_known: tuple[str, ...] = ()


def _normalize_abilities(raw: dict[str, int]) -> AbilityScores:
    out: dict[str, int] = {}
    for k, v in raw.items():
        key = _ABILITY_ALIASES.get(k, k)
        if key not in _LONG:
            raise ValueError(f"unknown ability key: {k!r}")
        out[key] = int(v)
    return AbilityScores(**out)


def make_build_spec(
    *,
    species_slug: str,
    class_slug: str,
    level: int = 1,
    subclass_slug: str | None = None,
    ability_scores: dict[str, int] | None = None,
    equipment: tuple[str, ...] = (),
    selected_choices: tuple[str, ...] = (),
) -> CharacterBuildSpec:
    return CharacterBuildSpec(
        species_slug=species_slug,
        class_slug=class_slug,
        level=level,
        subclass_slug=subclass_slug,
        ability_scores=_normalize_abilities(ability_scores or {}),
        equipment=equipment,
        selected_choices=selected_choices,
    )


__all__ = [
    "AbilityScores",
    "CharacterBuildSpec",
    "CombatInstance",
    "make_build_spec",
]
