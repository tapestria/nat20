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


class MonsterTraitMechanic(StrEnum):
    """Typed vocabulary for the most common SRD 5.2 monster traits.

    Foundry ships traits as prose-only ``type: feat`` items; this enum is the
    translator's name→mechanic table (``tools/translators/foundry.py::
    _TRAIT_MECHANICS``). Every other trait keeps ``mechanic=None`` and only
    its ``description`` (campaign design C22: typed vocabulary for the top
    traits, prose fallback for the rest).
    """

    MAGIC_RESISTANCE = "magic_resistance"
    LEGENDARY_RESISTANCE = "legendary_resistance"
    AMPHIBIOUS = "amphibious"
    PACK_TACTICS = "pack_tactics"
    SPIDER_CLIMB = "spider_climb"
    WATER_BREATHING = "water_breathing"
    SWARM = "swarm"
    RESTORATION = "restoration"  # Diabolical / Demonic / … Restoration variants
    FLYBY = "flyby"
    HOLD_BREATH = "hold_breath"
    SUNLIGHT_SENSITIVITY = "sunlight_sensitivity"
    UNDEAD_FORTITUDE = "undead_fortitude"
    REGENERATION = "regeneration"
    INCORPOREAL_MOVEMENT = "incorporeal_movement"


class MonsterAction(BaseModel):
    slug: str
    name: str
    kind: MonsterActionKind
    description: str
    activities: list[Activity] = Field(default_factory=list)
    recharge: str | None = None  # "5-6" for recharge actions
    legendary_cost: PositiveInt | None = None  # cost in legendary action points
    uses_per_day: PositiveInt | None = None
    mechanic: MonsterTraitMechanic | None = None
    """Typed trait mechanic for ``special_abilities`` entries the translator
    recognises (SRD 5.2 stat-block traits); ``None`` for actions and for
    prose-only traits."""


class MonsterTrait(BaseModel):
    """One de-duplicated SRD 5.2 monster trait (``canonical/traits/``), built
    from the embedded CC-BY feat items of the SRD actor documents."""

    slug: str
    name: str
    description: str
    mechanic: MonsterTraitMechanic | None = None
    provenance: Provenance
    review: ReviewState


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
