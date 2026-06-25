"""Shared schema building blocks for canonical SRD entries.

Activity sub-schema (Phase 7b PR A — task A3) mirrors Foundry's per-kind
data classes from ``raw_sources/foundry/module/data/activity/*-data.mjs``.
``Activity`` is a discriminated union of ten per-kind models keyed on the
``kind`` field (Foundry calls it ``type``); each per-kind model composes
shared field-block sub-models that wrap Foundry's ``shared/*-field.mjs``
contents (``ActivationField``, ``DurationField``, ``RangeField``,
``TargetField``, ``UsesField``, ``DamageField``, ``ConsumptionTargetsField``,
``AppliedEffectField``).

Naming convention: snake_case throughout the Python layer. The translator
(``tools/translators/foundry.py``, task A4) maps Foundry's camelCase
(``spellSlot`` / ``chatFlavor`` / ``includeBase``) into these names. The
underlying structure (``save.ability``, ``damage.parts[].denomination``,
``check.dc.calculation``) follows Foundry verbatim so the translator stays a
near-pass-through.

Spatial fields stay in feet (per PR A design spec §E); grid conversion
happens at Phase 8 resolution time, not at the data seam.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Annotated, Any, Literal, Union

from pydantic import (
    BaseModel,
    Field,
    NonNegativeInt,
    PositiveInt,
    field_serializer,
)


# ---------------------------------------------------------------------------
# Provenance / review state
# ---------------------------------------------------------------------------


class Provenance(BaseModel, frozen=True):
    """Where this entry came from. One source per entry; no field-level mixing."""

    source: Literal["foundry"]
    source_url: str
    ingest_date: date
    ingest_version: str
    srd_version: frozenset[Literal["5.1", "5.2"]]
    license_tag: Literal["CC-BY-4.0"] = "CC-BY-4.0"

    @field_serializer("srd_version")
    def _serialize_srd_version(self, value: frozenset[str]) -> list[str]:
        # frozenset → JSON list in deterministic (sorted) order so canonical
        # output is byte-stable across runs without external post-processing.
        return sorted(value)


class ReviewState(BaseModel):
    """Human-review state baked into the canonical entry itself."""

    known_divergence: str | None = None
    """Reviewer rationale when canonical values diverge from Foundry. Translator
    skips cross-check + preserves field values when set."""

    requires_user_decision: bool = False
    """Translator pauses regen for this slug until a human resolves."""


# ---------------------------------------------------------------------------
# Legacy weapon/range types (used by Weapon, MonsterAction — NOT activity).
# These are domain-typed value objects for top-level weapon stats; the
# activity sub-schema below carries its own RangeBlock / TargetBlock /
# DamagePartBlock that mirror Foundry's per-activity field structure.
# ---------------------------------------------------------------------------


class RangeUnits(StrEnum):
    FEET = "ft"
    MILES = "miles"
    SQUARES = "squares"


class Range(BaseModel, frozen=True):
    """Weapon/spell range at the item level. ``self`` and ``touch`` ignore
    value/units. Activity range lives in :class:`RangeBlock` instead."""

    kind: Literal["self", "touch", "melee", "ranged", "sight", "unlimited"]
    value: PositiveInt | None = None
    units: RangeUnits | None = None
    long: PositiveInt | None = None  # weapon long range; None for spells


class TargetTemplateShape(StrEnum):
    CIRCLE = "circle"
    CONE = "cone"
    CUBE = "cube"
    CYLINDER = "cylinder"
    LINE = "line"
    RECT = "rect"
    RAY = "ray"
    SPHERE = "sphere"


class TargetTemplate(BaseModel, frozen=True):
    """Item-level AoE shape (used by ``MonsterAction.activities[]`` legacy
    typed targets). Activity-internal templates live in
    :class:`TargetTemplateBlock`."""

    shape: TargetTemplateShape
    size: PositiveInt
    units: RangeUnits = RangeUnits.FEET


class Target(BaseModel, frozen=True):
    """Item-level target. Activity-internal targets live in
    :class:`TargetBlock`."""

    kind: Literal["self", "creature", "object", "space", "ally", "enemy"]
    count: PositiveInt | None = None
    template: TargetTemplate | None = None


class DamagePart(BaseModel, frozen=True):
    """Top-level weapon ``damage_parts`` entry. Activity damage-part shape
    is :class:`DamagePartBlock` (Foundry's ``DamageData``)."""

    dice: str  # "1d8", "2d6+3"
    damage_type: str  # "slashing", "fire", etc. — open vocab from SRD


# ---------------------------------------------------------------------------
# Activity discriminator enum (convenience re-export). Each per-kind class
# uses a ``Literal[...]`` value for its ``kind`` discriminator; pydantic v2's
# discriminated-union machinery binds on the literal, not the enum, since
# StrEnum-as-discriminator has been brittle across the 2.x line.
# ---------------------------------------------------------------------------


class ActivityKind(StrEnum):
    ATTACK = "attack"
    CAST = "cast"
    CHECK = "check"
    DAMAGE = "damage"
    ENCHANT = "enchant"
    HEAL = "heal"
    SAVE = "save"
    SUMMON = "summon"
    TRANSFORM = "transform"
    UTILITY = "utility"


# ---------------------------------------------------------------------------
# Shared field-block sub-models. Each mirrors a Foundry ``shared/<name>-field``
# or ``activity/fields/<name>`` schema. Frozen because they are value-typed.
# ---------------------------------------------------------------------------


class ActivationBlock(BaseModel, frozen=True):
    """Foundry ``shared/activation-field.mjs``."""

    type: str = ""
    value: NonNegativeInt | None = None
    condition: str = ""
    override: bool = False


class ScalingBlock(BaseModel, frozen=True):
    """Generic ``{mode, formula}`` scaling block used by consumption targets."""

    mode: str = ""
    formula: str = ""


class ConsumptionScalingBlock(BaseModel, frozen=True):
    """Foundry ``consumption.scaling`` — ``{allowed, max}``."""

    allowed: bool = False
    max: str = ""


class ConsumptionTargetEntry(BaseModel, frozen=True):
    """One entry of ``consumption.targets[]``.

    Foundry models ``ConsumptionTargetsField`` as an ``ArrayField`` of
    ``ConsumptionTargetData``. The polymorphism is on the ``type`` discriminator
    (``activityUses`` / ``itemUses`` / ``attribute`` / ``hitDice`` / ``material``
    / ``spellSlots``); the rest of the shape is uniform across types, so a
    single model with a ``type`` string suffices — no per-type subclass.
    """

    type: str
    target: str = ""
    value: str = "1"
    scaling: ScalingBlock = Field(default_factory=ScalingBlock)


class ConsumptionBlock(BaseModel, frozen=True):
    """Foundry ``base-activity.mjs`` ``consumption`` schema."""

    scaling: ConsumptionScalingBlock = Field(default_factory=ConsumptionScalingBlock)
    spell_slot: bool = True
    targets: list[ConsumptionTargetEntry] = Field(default_factory=list)


class DescriptionBlock(BaseModel, frozen=True):
    """Foundry ``description`` — currently only ``chatFlavor``."""

    chat_flavor: str = ""


class DurationBlock(BaseModel, frozen=True):
    """Foundry ``shared/duration-field.mjs`` + base-activity additions
    (``concentration``, ``override``)."""

    value: str | None = None  # FormulaField: deterministic string or None.
    units: str = "inst"
    special: str = ""
    concentration: bool = False
    override: bool = False


class RangeBlock(BaseModel, frozen=True):
    """Foundry ``shared/range-field.mjs`` + base-activity ``override``."""

    value: str | None = None  # FormulaField (deterministic string) or None.
    units: str = "self"
    special: str = ""
    override: bool = False


class TargetTemplateBlock(BaseModel, frozen=True):
    """Foundry ``target.template`` sub-block."""

    count: str = ""
    contiguous: bool = False
    stationary: bool = False
    type: str = ""
    size: str = ""
    width: str = ""
    height: str = ""
    units: str = "ft"


class TargetAffectsBlock(BaseModel, frozen=True):
    """Foundry ``target.affects`` sub-block."""

    count: str = ""
    type: str = ""
    choice: bool = False
    special: str = ""


class TargetBlock(BaseModel, frozen=True):
    """Foundry ``shared/target-field.mjs`` + base-activity additions
    (``override``, ``prompt``)."""

    template: TargetTemplateBlock = Field(default_factory=TargetTemplateBlock)
    affects: TargetAffectsBlock = Field(default_factory=TargetAffectsBlock)
    override: bool = False
    prompt: bool = True


class UsesRecoveryEntry(BaseModel, frozen=True):
    """One entry of ``uses.recovery[]``."""

    period: str = "lr"
    type: str = "recoverAll"
    formula: str = ""


class UsesBlock(BaseModel, frozen=True):
    """Foundry ``shared/uses-field.mjs``."""

    spent: NonNegativeInt = 0
    max: str = ""
    recovery: list[UsesRecoveryEntry] = Field(default_factory=list)


class VisibilityLevelBlock(BaseModel, frozen=True):
    """Foundry ``visibility.level`` ``{min, max}``."""

    min: NonNegativeInt | None = None
    max: NonNegativeInt | None = None


class VisibilityBlock(BaseModel, frozen=True):
    """Foundry ``base-activity.mjs`` ``visibility`` schema."""

    identifier: str = ""
    level: VisibilityLevelBlock = Field(default_factory=VisibilityLevelBlock)
    require_attunement: bool = False
    require_identification: bool = False
    require_magic: bool = False


class DamageCustomBlock(BaseModel, frozen=True):
    """``damage.parts[].custom`` — opt-in raw formula override."""

    enabled: bool = False
    formula: str = ""


class DamageScalingBlock(BaseModel, frozen=True):
    """``damage.parts[].scaling`` — per-part upcast/level scaling."""

    mode: str = ""
    number: NonNegativeInt | None = 1
    formula: str = ""


class DamagePartBlock(BaseModel, frozen=True):
    """Foundry ``shared/damage-field.mjs`` ``DamageData``. Also used as
    :class:`HealActivity.healing` since Foundry's heal activity stores
    healing as a single ``DamageField``."""

    number: NonNegativeInt | None = None
    denomination: NonNegativeInt | None = None
    bonus: str = ""
    types: list[str] = Field(default_factory=list)
    custom: DamageCustomBlock = Field(default_factory=DamageCustomBlock)
    scaling: DamageScalingBlock = Field(default_factory=DamageScalingBlock)


# Applied-effect references on an activity. Foundry's AppliedEffectField has
# per-kind extensions: SaveActivity adds ``onSave``; EnchantActivity adds
# ``riders``. Modeled as one class with optional extension fields to keep the
# discriminated-union narrow (the kind-level discriminator is on the parent
# activity; per-effect kind isn't a meaningful axis).


class EffectLevelBlock(BaseModel, frozen=True):
    """``effects[].level`` and ``visibility.level`` — both ``{min, max}``."""

    min: NonNegativeInt | None = None
    max: NonNegativeInt | None = None


class EnchantEffectRiders(BaseModel, frozen=True):
    """EnchantActivity ``effects[].riders`` — sets of activity/effect/item ids."""

    activity: list[str] = Field(default_factory=list)
    effect: list[str] = Field(default_factory=list)
    item: list[str] = Field(default_factory=list)


class AppliedEffectRef(BaseModel, frozen=True):
    """Foundry ``activity/fields/applied-effect-field.mjs`` reference. The
    ``id`` is a DocumentIdField pointer into the parent item's ``effects[]``.

    ``on_save`` is populated only by SaveActivity (Foundry adds the field via
    schema extension). ``riders`` is populated only by EnchantActivity. Both
    stay optional on the shared model rather than spawning per-kind subclasses
    — the cost would be two more types and a per-kind effects union for one
    extra field each.
    """

    id: str = Field(alias="_id", default="")
    level: EffectLevelBlock = Field(default_factory=EffectLevelBlock)
    on_save: bool | None = None
    riders: EnchantEffectRiders | None = None

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Per-kind activity-only blocks.
# ---------------------------------------------------------------------------


class AttackTypeBlock(BaseModel, frozen=True):
    """``attack.type`` — Foundry's melee/ranged × weapon/spell axis."""

    value: str = ""
    classification: str = ""


class AttackCriticalBlock(BaseModel, frozen=True):
    """``attack.critical`` — per-attack crit threshold override."""

    threshold: PositiveInt | None = None


class AttackBlock(BaseModel, frozen=True):
    """Foundry ``attack-data.mjs`` ``attack`` schema."""

    ability: str = ""
    bonus: str = ""
    critical: AttackCriticalBlock = Field(default_factory=AttackCriticalBlock)
    flat: bool = False
    type: AttackTypeBlock = Field(default_factory=AttackTypeBlock)


class AttackDamageCriticalBlock(BaseModel, frozen=True):
    """AttackActivity ``damage.critical`` — only ``bonus`` (no ``allow``)."""

    bonus: str = ""


class AttackDamageBlock(BaseModel, frozen=True):
    """AttackActivity ``damage`` — note ``includeBase`` is attack-specific."""

    critical: AttackDamageCriticalBlock = Field(default_factory=AttackDamageCriticalBlock)
    include_base: bool = True
    parts: list[DamagePartBlock] = Field(default_factory=list)


class SaveDcBlock(BaseModel, frozen=True):
    """``save.dc`` / ``check.dc`` shared shape."""

    calculation: str = ""
    formula: str = ""


class SaveBlock(BaseModel, frozen=True):
    """Foundry ``save-data.mjs`` ``save`` schema."""

    ability: list[str] = Field(default_factory=list)
    dc: SaveDcBlock = Field(default_factory=SaveDcBlock)


class SaveDamageCriticalBlock(BaseModel, frozen=True):
    """SaveActivity / DamageActivity ``damage.critical`` — ``{allow, bonus}``."""

    allow: bool = False
    bonus: str = ""


class SaveDamageBlock(BaseModel, frozen=True):
    """SaveActivity ``damage`` — note ``onSave`` is save-specific."""

    on_save: str = "half"
    parts: list[DamagePartBlock] = Field(default_factory=list)


class DamageActivityDamageBlock(BaseModel, frozen=True):
    """Standalone DamageActivity ``damage`` — has ``critical.allow`` but no
    ``onSave`` and no ``includeBase``."""

    critical: SaveDamageCriticalBlock = Field(default_factory=SaveDamageCriticalBlock)
    parts: list[DamagePartBlock] = Field(default_factory=list)


class CheckBlock(BaseModel, frozen=True):
    """Foundry ``check-data.mjs`` ``check`` schema."""

    ability: str = ""
    associated: list[str] = Field(default_factory=list)
    dc: SaveDcBlock = Field(default_factory=SaveDcBlock)


class CastChallengeBlock(BaseModel, frozen=True):
    """``spell.challenge`` — DC/attack overrides for a cast scroll."""

    attack: int | None = None
    save: int | None = None
    override: bool = False


class CastSpellBlock(BaseModel, frozen=True):
    """Foundry ``cast-data.mjs`` ``spell`` schema."""

    ability: str = ""
    challenge: CastChallengeBlock = Field(default_factory=CastChallengeBlock)
    level: NonNegativeInt | None = None
    properties: list[str] = Field(default_factory=lambda: ["vocal", "somatic", "material"])
    spellbook: bool = True
    uuid: str = ""


class EnchantRestrictionsBlock(BaseModel, frozen=True):
    """Foundry ``enchant-data.mjs`` ``restrictions`` schema."""

    allow_magical: bool = False
    categories: list[str] = Field(default_factory=list)
    properties: list[str] = Field(default_factory=list)
    type: str = ""


class EnchantEnchantBlock(BaseModel, frozen=True):
    """``enchant.enchant`` — pre-migration legacy ``identifier`` may still
    appear; post-migration only ``self`` survives."""

    self: bool = False
    identifier: str | None = None  # Legacy pre-migration field; preserved.


class SummonBonusesBlock(BaseModel, frozen=True):
    """Foundry ``summon-data.mjs`` ``bonuses`` schema."""

    ac: str = ""
    hd: str = ""
    hp: str = ""
    attack_damage: str = ""
    save_damage: str = ""
    healing: str = ""


class SummonMatchBlock(BaseModel, frozen=True):
    """Foundry ``summon-data.mjs`` ``match`` schema."""

    ability: str = ""
    attacks: bool = False
    disposition: bool = False
    proficiency: bool = False
    saves: bool = False


class SummonProfile(BaseModel, frozen=True):
    """One entry of ``summon.profiles[]`` (a creature template)."""

    id: str = Field(alias="_id", default="")
    count: str = ""
    cr: str = ""
    level: EffectLevelBlock = Field(default_factory=EffectLevelBlock)
    name: str = ""
    types: list[str] = Field(default_factory=list)
    uuid: str = ""

    model_config = {"populate_by_name": True}


class SummonSummonBlock(BaseModel, frozen=True):
    """``summon.summon`` — mode + prompt config; ``identifier`` is legacy
    pre-migration."""

    mode: str = ""
    prompt: bool = True
    identifier: str | None = None  # Legacy pre-migration field; preserved.


class TransformProfile(BaseModel, frozen=True):
    """One entry of ``transform.profiles[]`` (a transformation form)."""

    id: str = Field(alias="_id", default="")
    cr: str = ""
    level: EffectLevelBlock = Field(default_factory=EffectLevelBlock)
    movement: list[str] = Field(default_factory=list)
    name: str = ""
    sizes: list[str] = Field(default_factory=list)
    types: list[str] = Field(default_factory=list)
    uuid: str = ""

    model_config = {"populate_by_name": True}


class TransformBlock(BaseModel, frozen=True):
    """Foundry ``transform-data.mjs`` ``transform`` schema."""

    customize: bool = False
    mode: str = "cr"
    preset: str = ""
    identifier: str | None = None  # Legacy pre-migration field; preserved.


class RollBlock(BaseModel, frozen=True):
    """UtilityActivity / TransformActivity ``roll`` schema."""

    formula: str = ""
    name: str = ""
    prompt: bool = False
    visible: bool = False


# ---------------------------------------------------------------------------
# Per-kind activity models. Each composes the shared blocks above + its own
# kind-specific blocks. ``kind`` is a Literal discriminator (NOT ``ActivityKind``
# — pydantic v2 discriminated-union binding on a StrEnum has been brittle).
#
# Two-level base hierarchy:
# - ``_ActivityBase``: 13 fields Foundry's BaseActivityData ships unconditionally
#   (_id/name/img/sort/activation/consumption/description/duration/flags/range/
#   target/uses/visibility) + populate_by_name config. ``effects`` is NOT
#   declared here because Foundry's CastActivity legitimately omits it
#   (cast-data.mjs deletes it in defineSchema).
# - ``_ActivityBaseWithEffects(_ActivityBase)``: adds ``effects: list[
#   AppliedEffectRef]``. The 9 kinds Foundry ships with ``effects[]`` inherit
#   from this. CastActivity inherits from ``_ActivityBase`` directly.
#
# Pydantic v2 supports inheritance + discriminated unions cleanly: each
# subclass redeclares only ``kind: Literal[…] = "…"`` and per-kind blocks.
# Verified by round-trip + canonical regen byte-identical comparison.
# ---------------------------------------------------------------------------


class _ActivityBase(BaseModel):
    """Shared fields every Foundry activity carries (base-activity.mjs).
    Subclasses redeclare only the ``kind`` discriminator and per-kind blocks."""

    id: str = Field(alias="_id", default="")
    name: str = ""
    img: str = ""
    sort: int = 0
    activation: ActivationBlock = Field(default_factory=ActivationBlock)
    consumption: ConsumptionBlock = Field(default_factory=ConsumptionBlock)
    description: DescriptionBlock = Field(default_factory=DescriptionBlock)
    duration: DurationBlock = Field(default_factory=DurationBlock)
    flags: dict[str, Any] = Field(default_factory=dict)
    range: RangeBlock = Field(default_factory=RangeBlock)
    target: TargetBlock = Field(default_factory=TargetBlock)
    uses: UsesBlock = Field(default_factory=UsesBlock)
    visibility: VisibilityBlock = Field(default_factory=VisibilityBlock)

    model_config = {"populate_by_name": True}


class _ActivityBaseWithEffects(_ActivityBase):
    """Adds the ``effects[]`` list every Foundry activity except CastActivity
    carries. CastActivity inherits from :class:`_ActivityBase` directly."""

    effects: list[AppliedEffectRef] = Field(default_factory=list)


class AttackActivity(_ActivityBaseWithEffects):
    """Foundry ``attack-data.mjs``. Resolver: roll attack vs AC, on hit
    roll damage; ``include_base`` controls weapon base-damage inclusion."""

    kind: Literal["attack"] = "attack"
    attack: AttackBlock = Field(default_factory=AttackBlock)
    damage: AttackDamageBlock = Field(default_factory=AttackDamageBlock)


class CastActivity(_ActivityBase):
    """Foundry ``cast-data.mjs``. Wraps another spell item (``spell.uuid``)
    so a scroll/wand can cast a referenced spell with its own DC/attack
    overrides. Note: cast activities have NO ``effects[]`` (Foundry deletes
    the field in defineSchema)."""

    kind: Literal["cast"] = "cast"
    spell: CastSpellBlock = Field(default_factory=CastSpellBlock)


class CheckActivity(_ActivityBaseWithEffects):
    """Foundry ``check-data.mjs``. Roll an ability/skill/tool check against
    a DC."""

    kind: Literal["check"] = "check"
    check: CheckBlock = Field(default_factory=CheckBlock)


class DamageActivity(_ActivityBaseWithEffects):
    """Foundry ``damage-data.mjs``. Unconditional damage (no attack roll, no
    save) — environmental, retributive strike, etc."""

    kind: Literal["damage"] = "damage"
    damage: DamageActivityDamageBlock = Field(default_factory=DamageActivityDamageBlock)


class EnchantActivity(_ActivityBaseWithEffects):
    """Foundry ``enchant-data.mjs``. Applies an enchantment ActiveEffect to a
    target item; ``effects[]`` carries per-effect rider refs."""

    kind: Literal["enchant"] = "enchant"
    enchant: EnchantEnchantBlock = Field(default_factory=EnchantEnchantBlock)
    restrictions: EnchantRestrictionsBlock = Field(default_factory=EnchantRestrictionsBlock)


class HealActivity(_ActivityBaseWithEffects):
    """Foundry ``heal-data.mjs``. ``healing`` is a single ``DamagePartBlock``
    (Foundry stores it as a ``DamageField`` directly, not inside an array)."""

    kind: Literal["heal"] = "heal"
    healing: DamagePartBlock = Field(default_factory=DamagePartBlock)


class SaveActivity(_ActivityBaseWithEffects):
    """Foundry ``save-data.mjs``. Target makes a saving throw vs DC;
    ``damage.on_save`` controls half/none on success. ``effects[]`` uses the
    save-extended :class:`AppliedEffectRef` (``on_save`` field populated)."""

    kind: Literal["save"] = "save"
    damage: SaveDamageBlock = Field(default_factory=SaveDamageBlock)
    save: SaveBlock = Field(default_factory=SaveBlock)


class SummonActivity(_ActivityBaseWithEffects):
    """Foundry ``summon-data.mjs``. Summons one or more creature profiles."""

    kind: Literal["summon"] = "summon"
    bonuses: SummonBonusesBlock = Field(default_factory=SummonBonusesBlock)
    creature_sizes: list[str] = Field(default_factory=list)
    creature_types: list[str] = Field(default_factory=list)
    match: SummonMatchBlock = Field(default_factory=SummonMatchBlock)
    profiles: list[SummonProfile] = Field(default_factory=list)
    summon: SummonSummonBlock = Field(default_factory=SummonSummonBlock)
    temp_hp: str = ""


class TransformActivity(_ActivityBaseWithEffects):
    """Foundry ``transform-data.mjs``. Polymorph-style transformation;
    ``settings`` is Foundry's ``TransformationSetting`` embedded blob —
    preserved as opaque dict at this layer (resolver decodes)."""

    kind: Literal["transform"] = "transform"
    profiles: list[TransformProfile] = Field(default_factory=list)
    roll: RollBlock = Field(default_factory=RollBlock)
    settings: dict[str, Any] | None = None
    transform: TransformBlock = Field(default_factory=TransformBlock)


class UtilityActivity(_ActivityBaseWithEffects):
    """Foundry ``utility-data.mjs``. Generic roll-a-formula or do-nothing
    fallback when other kinds don't fit."""

    kind: Literal["utility"] = "utility"
    roll: RollBlock = Field(default_factory=RollBlock)


# ---------------------------------------------------------------------------
# Discriminated union. ``list[Activity]`` on Item/Spell/MonsterAction validates
# each element against the kind-keyed variant.
# ---------------------------------------------------------------------------


Activity = Annotated[
    Union[
        AttackActivity,
        CastActivity,
        CheckActivity,
        DamageActivity,
        EnchantActivity,
        HealActivity,
        SaveActivity,
        SummonActivity,
        TransformActivity,
        UtilityActivity,
    ],
    Field(discriminator="kind"),
]


# ---------------------------------------------------------------------------
# Creature movement / senses / passive effects (unchanged from Phase 7a).
# ---------------------------------------------------------------------------


class Movement(BaseModel, frozen=True):
    """Creature movement modes in feet. ``None`` = mode unavailable."""

    walk: NonNegativeInt | None = None
    fly: NonNegativeInt | None = None
    swim: NonNegativeInt | None = None
    burrow: NonNegativeInt | None = None
    climb: NonNegativeInt | None = None
    hover: bool = False


class PassiveEffectChange(BaseModel, frozen=True):
    """One entry in a Foundry ActiveEffect's ``changes`` list — a key/mode/value
    triple that mutates an actor field while the effect is active.

    ``mode`` mirrors Foundry's ``CONST.ACTIVE_EFFECT_MODES`` enum:
    0 = custom, 1 = multiply, 2 = add, 3 = downgrade, 4 = upgrade, 5 = override.

    ``value`` is always typed as a string in Foundry (e.g. ``"+1"``, ``"19"``,
    ``"1d6"``); the resolver decides how to parse it per ``key`` semantics.
    """

    key: str
    mode: int
    value: str
    priority: int | None = None


class PassiveEffect(BaseModel):
    """A Foundry top-level ``effects[]`` entry. Drives passive ActiveEffect
    modifiers that the resolver applies while an item is worn/attuned (e.g.
    Cloak of Protection's ``+1`` to AC and saves).

    Activity-resolution (Phase 7b engine) consumes these; Phase 7a only
    preserves them so canonical → consumer is lossless.

    ``id`` (Foundry ``_id``) is the join key that ``AppliedEffectRef`` points at
    via ``activity.effects[].id``; the resolver follows that pointer to locate
    the effect rider to apply. ``statuses`` is Foundry's condition mechanism — a
    list of SRD condition ids (e.g. ``["paralyzed"]``) the effect imposes while
    active; the Phase 7b resolver consumes them to apply conditions.
    """

    id: str = Field(alias="_id", default="")
    name: str = ""
    description: str = ""
    changes: list[PassiveEffectChange] = Field(default_factory=list)
    statuses: list[str] = Field(default_factory=list)
    duration: dict[str, Any] | None = None
    disabled: bool = False
    transfer: bool = True

    model_config = {"populate_by_name": True}


class Senses(BaseModel, frozen=True):
    """Creature senses in feet. ``None`` = sense unavailable."""

    darkvision: NonNegativeInt | None = None
    blindsight: NonNegativeInt | None = None
    tremorsense: NonNegativeInt | None = None
    truesight: NonNegativeInt | None = None
    passive_perception: NonNegativeInt | None = None
