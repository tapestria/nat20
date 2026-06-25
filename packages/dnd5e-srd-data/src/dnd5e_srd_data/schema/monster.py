"""Monster + MonsterAction schema."""

from enum import StrEnum

from pydantic import BaseModel, Field, PositiveInt

from dnd5e_srd_data.schema.common import (
    Activity,
    Movement,
    Provenance,
    ReviewState,
    Senses,
)

# Alias avoids shadowing the builtin inside models that use `int` as a field name
# (ability score keys per Foundry schema collide with class-body name resolution).
_Int = int


class CreatureType(StrEnum):
    ABERRATION = "aberration"
    BEAST = "beast"
    CELESTIAL = "celestial"
    CONSTRUCT = "construct"
    DRAGON = "dragon"
    ELEMENTAL = "elemental"
    FEY = "fey"
    FIEND = "fiend"
    GIANT = "giant"
    HUMANOID = "humanoid"
    MONSTROSITY = "monstrosity"
    OOZE = "ooze"
    PLANT = "plant"
    UNDEAD = "undead"


class CreatureSize(StrEnum):
    TINY = "tiny"
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    HUGE = "huge"
    GARGANTUAN = "gargantuan"


class AbilityScores(BaseModel, frozen=True):
    str: PositiveInt
    dex: PositiveInt
    con: PositiveInt
    int: PositiveInt
    wis: PositiveInt
    cha: PositiveInt


class SavingThrowProficiencies(BaseModel, frozen=True):
    """Saving throw bonuses for proficient saves. ``None`` = not proficient
    (caller uses raw ability mod)."""

    str: _Int | None = None
    dex: _Int | None = None
    con: _Int | None = None
    int: _Int | None = None
    wis: _Int | None = None
    cha: _Int | None = None


class SkillProficiencies(BaseModel):
    """Skill bonuses for proficient skills. Foundry's skill set; open vocab."""

    model_config = {"extra": "allow"}  # Foundry sometimes ships rare skills

    acrobatics: int | None = None
    animal_handling: int | None = None
    arcana: int | None = None
    athletics: int | None = None
    deception: int | None = None
    history: int | None = None
    insight: int | None = None
    intimidation: int | None = None
    investigation: int | None = None
    medicine: int | None = None
    nature: int | None = None
    perception: int | None = None
    performance: int | None = None
    persuasion: int | None = None
    religion: int | None = None
    sleight_of_hand: int | None = None
    stealth: int | None = None
    survival: int | None = None


class MonsterActionKind(StrEnum):
    ACTION = "action"
    BONUS_ACTION = "bonus_action"
    REACTION = "reaction"
    LEGENDARY = "legendary"
    LAIR = "lair"
    REGIONAL = "regional"
    SPECIAL = "special"  # traits, abilities


class MonsterAction(BaseModel):
    slug: str
    name: str
    kind: MonsterActionKind
    description: str
    activities: list[Activity] = Field(default_factory=list)
    recharge: str | None = None  # "5-6" for recharge actions
    legendary_cost: PositiveInt | None = None  # cost in legendary action points
    uses_per_day: PositiveInt | None = None


class Monster(BaseModel):
    slug: str
    name: str
    description: str

    creature_type: CreatureType
    creature_size: CreatureSize
    alignment: str | None = None

    ac: PositiveInt | None = None
    hp: PositiveInt
    hp_dice: str

    ability_scores: AbilityScores
    movement: Movement
    senses: Senses

    cr: float
    proficiency_bonus: PositiveInt

    saving_throws: SavingThrowProficiencies
    skills: SkillProficiencies

    damage_resistances: list[str] = Field(default_factory=list)
    damage_immunities: list[str] = Field(default_factory=list)
    damage_vulnerabilities: list[str] = Field(default_factory=list)
    condition_immunities: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)

    actions: list[MonsterAction] = Field(default_factory=list)
    legendary_actions: list[MonsterAction] = Field(default_factory=list)
    lair_actions: list[MonsterAction] = Field(default_factory=list)
    special_abilities: list[MonsterAction] = Field(default_factory=list)

    provenance: Provenance
    review: ReviewState
