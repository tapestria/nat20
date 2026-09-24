"""The build-spec contract: the typed input that resolves into a complete PC.

A 7c test/seed factory produces these now; the char-creation build-core (CharacterDraft,
spec-only today) becomes a second producer of the identical contract later. Resolution
(build_party_member) is pure; selection (who fills the build-spec) is the producer's job.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from dnd5e_srd_data.loader import AssetLoader
from dnd5e_srd_data.schema.advancement import AdvancementEntry
from dnd5e_srd_data.schema.background import Background
from dnd5e_srd_data.schema.class_ import Class, Subclass
from dnd5e_srd_data.schema.common import PassiveEffectChange
from dnd5e_srd_data.schema.item import Armor
from dnd5e_srd_data.schema.species import Species
from pydantic import BaseModel, ConfigDict, Field, model_validator

from dnd5e_engine.activities.passive_stats import (
    CombatantMovementModes,
    CombatantSenses,
    interpret_passive_stats,
)
from dnd5e_engine.events import Ability
from dnd5e_engine.rules.character import (
    ABILITY_NAME_BY_CODE,
    MAX_ATTUNED_ITEMS,
    AbilityName,
    AbilityScoreMethod,
    AcCalcMode,
    ArmorTraining,
    HpMode,
    ProficiencyGrants,
    ability_score_improvement,
    ac_mode_eligible,
    ac_modes_from_changes,
    apply_ability_increases,
    armor_class,
    armor_speed_penalty,
    armor_training_from_changes,
    extra_attack_count,
    has_flag,
    hit_dice_pool,
    hit_die_size,
    hit_point_bonus,
    hit_points_max,
    leveled_feature_slugs,
    proficiency_grants,
    subclass_gate_level,
    validate_ability_score_method,
    validate_increase_budget,
    weapon_proficiencies_from_changes,
)
from dnd5e_engine.rules.choices import ParsedChoices, parse_selected_choices
from dnd5e_engine.rules.dice import ability_modifier, proficiency_bonus
from dnd5e_engine.rules.skills import SKILL_CODE_TO_SLUG, Skill, passive_perception
from dnd5e_engine.spellcasting import (
    SpellcastingProgression,
    derive_pact_slots,
    derive_spell_slots,
    multiclass_caster_level,
    slots_for_caster_level,
)

# Long-form -> the canonical field; short-form aliases the backend cache / lib may pass.
# A plain ``dict(ABILITY_NAME_BY_CODE)`` keeps the source's Literal key/value types,
# which mypy then rejects at ``_normalize_abilities``'s ``str`` lookups (dict is
# invariant); the comprehension widens both to ``str`` at the assignment.
_ABILITY_ALIASES: dict[str, str] = {code: name for code, name in ABILITY_NAME_BY_CODE.items()}
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
    """The typed input that resolves into a complete PC.

    C17: ``classes`` is the multiclass carrier (spec §3) — a ``{class_slug: level}``
    map. ``class_slug`` (= the FIRST key, the primary class) and ``level`` (= the SUM
    of class levels) are kept as single-class aliases and always populated, so
    existing single-class callers (``CharacterBuildSpec(class_slug=..., level=...)``)
    keep working exactly as before.

    Caveat: ``model_copy(update=...)`` bypasses the ``mode="before"``
    validator below (Pydantic does not re-run before-validators on
    ``model_copy``), so a ``model_copy`` that changes only ``level`` or only
    ``classes`` can desync the two fields. Construct a fresh
    ``CharacterBuildSpec(...)`` instead of ``model_copy`` when changing
    either field.

    C19 derivation inputs — see ``derive_sheet``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    species_slug: str
    class_slug: str = ""
    classes: dict[str, int] = Field(default_factory=dict)
    subclass_slug: str | None = None
    level: int = Field(ge=1, le=20, default=1)
    ability_scores: AbilityScores = Field(default_factory=AbilityScores)
    equipment: tuple[str, ...] = ()
    selected_choices: tuple[str, ...] = ()
    background_slug: str | None = None
    hp_mode: HpMode = "fixed"
    # Host-recorded Hit Die results per class for ``hp_mode="rolled"``: the
    # first class records ``level - 1`` rolls (its level 1 is the maximum),
    # every other class ``level``. Recorded, never re-rolled, so a sheet
    # re-derives identically.
    hp_rolls: dict[str, tuple[int, ...]] = Field(default_factory=dict)
    # ``None`` lets derive_sheet pick the best mode the character's features and
    # worn equipment allow; a value forces that mode (SRD 5.2: "you can benefit
    # from only one at a time").
    ac_calc_mode: AcCalcMode | None = None
    attuned_items: tuple[str, ...] = ()
    ability_score_method: AbilityScoreMethod | None = None

    @model_validator(mode="before")
    @classmethod
    def _reconcile_classes(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        data = dict(data)
        classes = dict(data.get("classes") or {})
        class_slug = data.get("class_slug")
        level = data.get("level")
        if classes:
            for slug, lvl in classes.items():
                if not isinstance(lvl, int) or lvl < 1:
                    raise ValueError(
                        f"class level for {slug!r} must be a positive int, got {lvl!r}"
                    )
            total = sum(classes.values())
            primary = next(iter(classes))
            if class_slug and class_slug not in classes:
                raise ValueError(
                    f"class_slug {class_slug!r} is not one of classes {sorted(classes)}"
                )
            if level is not None and level != total:
                raise ValueError(f"level {level} does not equal the sum of classes ({total})")
            data["class_slug"] = class_slug or primary
            data["level"] = total
            data["classes"] = classes
        elif class_slug:
            data["classes"] = {class_slug: level if level is not None else 1}
        else:
            raise ValueError("CharacterBuildSpec needs class_slug or classes")
        return data


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
    # SRD Pact Magic — the Warlock's separately-recovering slot pool
    # ``{slot_level: count_remaining}``; consumed by the orchestrator in C17 Task 3.
    pact_slots: dict[int, int] = Field(default_factory=dict)
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
    class_slug: str | None = None,
    level: int | None = None,
    classes: Mapping[str, int] | None = None,
    subclass_slug: str | None = None,
    ability_scores: dict[str, int] | None = None,
    equipment: tuple[str, ...] = (),
    selected_choices: tuple[str, ...] = (),
    background_slug: str | None = None,
    hp_mode: HpMode = "fixed",
    hp_rolls: Mapping[str, Sequence[int]] | None = None,
    ac_calc_mode: AcCalcMode | None = None,
    attuned_items: tuple[str, ...] = (),
    ability_score_method: AbilityScoreMethod | None = None,
) -> CharacterBuildSpec:
    payload: dict[str, Any] = {
        "species_slug": species_slug,
        "subclass_slug": subclass_slug,
        "ability_scores": _normalize_abilities(ability_scores or {}),
        "equipment": equipment,
        "selected_choices": selected_choices,
        "background_slug": background_slug,
        "hp_mode": hp_mode,
        "hp_rolls": {k: tuple(v) for k, v in (hp_rolls or {}).items()},
        "ac_calc_mode": ac_calc_mode,
        "attuned_items": attuned_items,
        "ability_score_method": ability_score_method,
    }
    if classes:
        payload["classes"] = dict(classes)
    if class_slug is not None:
        payload["class_slug"] = class_slug
    if level is not None:
        payload["level"] = level
    return CharacterBuildSpec(**payload)


def _progressions(
    classes: Mapping[str, int], loader: AssetLoader
) -> dict[str, tuple[SpellcastingProgression, int]]:
    out: dict[str, tuple[SpellcastingProgression, int]] = {}
    for slug, lvl in classes.items():
        cls = loader.get_class(slug)
        if cls is None:
            raise ValueError(f"unknown class: {slug!r}")
        out[slug] = (cast(SpellcastingProgression, str(cls.spellcasting.progression)), lvl)
    return out


def derive_multiclass_slots(
    classes: Mapping[str, int], *, loader: AssetLoader | None = None
) -> dict[int, int]:
    """Multiclass Spellcasting-feature slots for a ``{class_slug: level}`` map.

    Reads each class's ``spellcasting.progression`` through ``loader`` (default:
    the configured lib loader), applies the SRD per-class rounding (R2) and looks
    the total up in the Multiclass Spellcaster table. A single-class map returns
    exactly ``derive_spell_slots(...)`` for that class.
    """
    if loader is None:
        from dnd5e_engine.lib_loader import get_lib_loader

        loader = get_lib_loader()
    return slots_for_caster_level(multiclass_caster_level(_progressions(classes, loader)))


def derive_multiclass_pact_slots(
    classes: Mapping[str, int], *, loader: AssetLoader | None = None
) -> dict[int, int]:
    """Pact Magic pool for the ``pact``-progression class levels in ``classes`` (``{}`` if none)."""
    if loader is None:
        from dnd5e_engine.lib_loader import get_lib_loader

        loader = get_lib_loader()
    pact_levels = [lvl for prog, lvl in _progressions(classes, loader).values() if prog == "pact"]
    return derive_pact_slots(sum(pact_levels)) if pact_levels else {}


_log = logging.getLogger(__name__)

_LeveledSource = tuple[Class | Subclass | Species | None, int]


class DerivedSheet(BaseModel):
    """Everything ``derive_sheet`` derives from a ``CharacterBuildSpec``.

    Vocabularies match the engine inputs a host feeds next: ability modifiers
    keyed by the long ability name (the ``AbilityScores`` fields), save
    proficiencies by 3-letter ``Ability`` code and skills by long-form slug —
    as ``PartyMemberSpec`` and ``CheckSpec`` take them.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    ability_scores: AbilityScores
    ability_modifiers: dict[AbilityName, int]
    proficiency_bonus: int
    base_speed: int
    movement_modes: CombatantMovementModes
    senses: CombatantSenses
    damage_resistances: tuple[str, ...]
    damage_immunities: tuple[str, ...]
    condition_immunities: tuple[str, ...]
    save_proficiencies: frozenset[Ability]
    skill_proficiencies: frozenset[Skill]
    skill_expertise: frozenset[Skill]
    weapon_proficiencies: frozenset[str]
    armor_training: frozenset[ArmorTraining]
    passive_perception: int
    jack_of_all_trades: bool
    reliable_talent: bool
    stealth_disadvantage: bool
    extra_attack_count: int
    features: tuple[str, ...]
    feats: tuple[str, ...]
    spell_slots: dict[int, int]
    pact_slots: dict[int, int]
    hp_max: int
    hit_dice: dict[int, int]
    ac: int
    ac_calc_mode: AcCalcMode


def _class_docs(classes: Mapping[str, int], loader: AssetLoader) -> dict[str, Class]:
    docs: dict[str, Class] = {}
    for slug in classes:
        cls = loader.get_class(slug)
        if cls is None:
            raise ValueError(f"unknown class: {slug!r}")
        docs[slug] = cls
    return docs


def _species(slug: str, loader: AssetLoader) -> Species:
    species = loader.get_species(slug)
    if species is None:
        raise ValueError(f"unknown species: {slug!r}")
    return species


def _subclass(
    spec: CharacterBuildSpec, class_docs: Mapping[str, Class], loader: AssetLoader
) -> tuple[Subclass | None, int]:
    """The subclass and its owning class's level. SRD 5.2 grants a subclass at
    the class's ``Subclass`` advancement level, so naming one earlier is not a
    legal build; a multiclass subclass may belong to any class taken."""
    if spec.subclass_slug is None:
        return None, 0
    sub = loader.get_subclass(spec.subclass_slug)
    if sub is None:
        raise ValueError(f"unknown subclass: {spec.subclass_slug!r}")
    owner = sub.class_identifier
    if owner not in spec.classes:
        raise ValueError(
            f"subclass {spec.subclass_slug!r} is not a subclass of any of {sorted(spec.classes)}"
        )
    gate = subclass_gate_level(class_docs[owner])
    level = spec.classes[owner]
    if gate is not None and level < gate:
        raise ValueError(
            f"subclass {spec.subclass_slug!r} needs {owner} level {gate}; the build has {level}"
        )
    return sub, level


def _always_on_changes(features: Sequence[str], loader: AssetLoader) -> list[PassiveEffectChange]:
    """Changes of every always-on passive effect (``transfer`` and not
    ``disabled``) on the character's features. An unresolved slug is logged and
    skipped: a dataset gap must not block a sheet."""
    changes: list[PassiveEffectChange] = []
    for slug in features:
        feature = loader.get_feature(slug)
        if feature is None:
            _log.warning(
                "derive_sheet: granted feature slug did not resolve to a canonical "
                "feature; skipping",
                extra={"granted_feature_slug": slug},
            )
            continue
        for passive in feature.passive_effects:
            if passive.transfer and not passive.disabled:
                changes.extend(passive.changes)
    return changes


def _hit_points(
    spec: CharacterBuildSpec,
    die_sizes: Mapping[str, int],
    con_modifier: int,
    changes: Sequence[PassiveEffectChange],
) -> int:
    if spec.hp_mode == "fixed" and spec.hp_rolls:
        raise ValueError("hp_rolls given with hp_mode='fixed'; set hp_mode='rolled' to use them")
    rolls = spec.hp_rolls if spec.hp_mode == "rolled" else None
    return hit_points_max(spec.classes, die_sizes, con_modifier, rolls=rolls) + hit_point_bonus(
        changes, total_level=spec.level, classes=spec.classes
    )


def _background(slug: str | None, loader: AssetLoader) -> Background | None:
    if slug is None:
        return None
    background = loader.get_background(slug)
    if background is None:
        raise ValueError(f"unknown background: {slug!r}")
    return background


def _skills(
    grants: ProficiencyGrants, background: Background | None, choices: ParsedChoices
) -> tuple[frozenset[Skill], frozenset[Skill]]:
    skills = set(grants.skills) | set(choices.skills)
    if background is not None:
        skills |= {
            SKILL_CODE_TO_SLUG[c] for c in background.skill_proficiencies if c in SKILL_CODE_TO_SLUG
        }
    for skill in choices.expertise:
        if skill not in skills:
            raise ValueError(f"Expertise in {skill} needs proficiency in {skill}")
    return frozenset(skills), frozenset(choices.expertise)


def _choice_options(level_sources: Sequence[_LeveledSource]) -> dict[str, str]:
    """Every option of every feature-choice pool the build has reached (a pool
    opens at its first schedule level with a non-zero count) → its ref type."""
    options: dict[str, str] = {}
    for source, level in level_sources:
        if source is None:
            continue
        for choice in source.feature_choices:
            if any(step.count > 0 and step.level <= level for step in choice.schedule):
                for option in choice.pool:
                    options.setdefault(option.slug, option.ref_type)
    return options


def _split_picks(picks: Sequence[str], options: Mapping[str, str]) -> tuple[list[str], list[str]]:
    features: list[str] = []
    feats: list[str] = []
    for slug in picks:
        ref_type = options.get(slug)
        if ref_type is None:
            raise ValueError(
                f"selected_choices pick {slug!r} is not an option of any feature choice "
                "this build has reached"
            )
        (feats if ref_type == "feat" else features).append(slug)
    return features, feats


def _asi_slot(
    kind: str,
    class_slug: str,
    level: int,
    spec: CharacterBuildSpec,
    class_docs: Mapping[str, Class],
    used: set[tuple[str, int]],
) -> AdvancementEntry:
    token = f"{kind}:{class_slug}:{level}"
    if class_slug not in spec.classes:
        raise ValueError(
            f"{token}: {class_slug!r} is not one of the build's classes {sorted(spec.classes)}"
        )
    if level > spec.classes[class_slug]:
        raise ValueError(
            f"{token} needs {class_slug} level {level}; the build has {spec.classes[class_slug]}"
        )
    entry = ability_score_improvement(class_docs[class_slug], level)
    if entry is None:
        raise ValueError(
            f"{token}: there is no Ability Score Improvement at {class_slug} level {level}"
        )
    if (class_slug, level) in used:
        raise ValueError(
            f"the Ability Score Improvement at {class_slug} level {level} is already used"
        )
    used.add((class_slug, level))
    return entry


def _ability_scores(
    spec: CharacterBuildSpec,
    choices: ParsedChoices,
    class_docs: Mapping[str, Class],
    background: Background | None,
    used: set[tuple[str, int]],
) -> dict[AbilityName, int]:
    """Base scores, the background adjustment, then each ASI in token order."""
    scores = cast(dict[AbilityName, int], spec.ability_scores.model_dump())
    if spec.ability_score_method is not None:
        validate_ability_score_method(scores, spec.ability_score_method)
    if choices.background is not None:
        if background is None:
            raise ValueError("a background: choice needs background_slug")
        options = background.ability_options
        source = f"background {background.slug!r}"
        validate_increase_budget(
            choices.background,
            allowed={ABILITY_NAME_BY_CODE[code] for code in options.options},
            points=options.points,
            cap=options.cap,
            source=source,
        )
        scores = apply_ability_increases(scores, choices.background, source=source)
    all_names = set(ABILITY_NAME_BY_CODE.values())
    for pick in choices.asis:
        config = _asi_slot("asi", pick.class_slug, pick.level, spec, class_docs, used).configuration
        locked = {
            ABILITY_NAME_BY_CODE[c] for c in config.get("locked") or () if c in ABILITY_NAME_BY_CODE
        }
        source = f"asi:{pick.class_slug}:{pick.level}"
        validate_increase_budget(
            pick.increases,
            allowed=all_names - locked,
            points=int(config.get("points") or 0),
            cap=int(config.get("cap") or 2),
            source=source,
        )
        scores = apply_ability_increases(scores, pick.increases, source=source)
    return scores


def _asi_level_feats(
    spec: CharacterBuildSpec,
    choices: ParsedChoices,
    class_docs: Mapping[str, Class],
    used: set[tuple[str, int]],
    owned: set[str],
    loader: AssetLoader,
) -> list[str]:
    feats: list[str] = []
    for pick in choices.feats:
        _asi_slot("feat", pick.class_slug, pick.level, spec, class_docs, used)
        feat = loader.get_feat(pick.feat_slug)
        if feat is None:
            raise ValueError(f"unknown feat: {pick.feat_slug!r}")
        for prerequisite in feat.prerequisites:
            if prerequisite.level is not None and spec.level < prerequisite.level:
                raise ValueError(
                    f"feat {feat.slug!r} needs character level {prerequisite.level}; "
                    f"the build has {spec.level}"
                )
            missing = sorted(set(prerequisite.feats) - owned)
            if missing:
                raise ValueError(f"feat {feat.slug!r} needs {missing}")
        feats.append(feat.slug)
    return feats


@dataclass(frozen=True)
class _Worn:
    body: Armor | None
    body_bonus: int
    shield: Armor | None
    shield_bonus: int


def _attuned(spec: CharacterBuildSpec, loader: AssetLoader) -> frozenset[str]:
    attuned = spec.attuned_items
    if len(set(attuned)) != len(attuned):
        raise ValueError(f"attuned_items repeats an item: {sorted(attuned)}")
    if len(attuned) > MAX_ATTUNED_ITEMS:
        raise ValueError(
            f"attuned_items has {len(attuned)} items; SRD 5.2 allows no more than three"
        )
    for slug in attuned:
        if slug not in spec.equipment:
            raise ValueError(f"attuned item {slug!r} is not in equipment")
        item = loader.get_item(slug)
        if item is None:
            raise ValueError(f"unknown item: {slug!r}")
        if not item.requires_attunement:
            raise ValueError(f"{slug!r} does not require attunement")
    return frozenset(attuned)


def _worn(
    spec: CharacterBuildSpec, loader: AssetLoader, training: frozenset[ArmorTraining]
) -> _Worn:
    """Worn body armor and wielded Shield. SRD 5.2: "A creature can wear only one
    suit of armor at a time and wield only one Shield at a time"; "You gain the
    Armor Class benefit of a Shield only if you have training with it". A magic
    bonus counts once the item is attuned, when it requires attunement."""
    attuned = _attuned(spec, loader)
    body: list[Armor] = []
    shields: list[Armor] = []
    for slug in spec.equipment:
        armor = loader.get_armor(slug)
        if armor is not None:
            (shields if armor.armor_category == "shield" else body).append(armor)
    if len(body) > 1:
        raise ValueError(f"equipment wears more than one suit of armor: {[a.slug for a in body]}")
    if len(shields) > 1:
        raise ValueError(f"equipment wields more than one Shield: {[a.slug for a in shields]}")

    def bonus(armor: Armor) -> int:
        active = not armor.requires_attunement or armor.slug in attuned
        return armor.magical_bonus if active else 0

    worn_body = body[0] if body else None
    shield = shields[0] if shields else None
    shield_bonus = shield.base_ac + bonus(shield) if shield and "shield" in training else 0
    return _Worn(worn_body, bonus(worn_body) if worn_body else 0, shield, shield_bonus)


def _ac_mode(
    explicit: AcCalcMode | None,
    changes: Sequence[PassiveEffectChange],
    modifiers: Mapping[AbilityName, int],
    worn: _Worn,
) -> AcCalcMode:
    wearing, shielded = worn.body is not None, worn.shield is not None
    if explicit is not None:
        if not ac_mode_eligible(explicit, wearing_armor=wearing, wielding_shield=shielded):
            raise ValueError(
                f"ac_calc_mode {explicit!r} does not apply with the worn equipment "
                f"({[a.slug for a in (worn.body, worn.shield) if a]})"
            )
        return explicit
    eligible = sorted(
        mode
        for mode in ac_modes_from_changes(changes)
        if ac_mode_eligible(mode, wearing_armor=wearing, wielding_shield=shielded)
    )
    return max(
        eligible,
        key=lambda mode: armor_class(
            mode,
            modifiers,
            body_armor=worn.body,
            body_armor_bonus=worn.body_bonus,
            shield_bonus=worn.shield_bonus,
        ),
    )


def derive_sheet(spec: CharacterBuildSpec, *, loader: AssetLoader) -> DerivedSheet:
    """Derive the character sheet a ``CharacterBuildSpec`` describes (SRD 5.2
    Character Creation, Level Advancement and Multiclassing).

    Pure apart from ``loader`` reads; draws no dice. Raises ``ValueError`` for an
    unknown slug or a build the SRD forbids.
    """
    choices = parse_selected_choices(spec.selected_choices)
    class_docs = _class_docs(spec.classes, loader)
    species = _species(spec.species_slug, loader)
    subclass, subclass_level = _subclass(spec, class_docs, loader)
    background = _background(spec.background_slug, loader)
    level_sources: list[_LeveledSource] = [
        *((class_docs[slug], level) for slug, level in spec.classes.items()),
        (subclass, subclass_level),
        (species, spec.level),
    ]
    picked_features, picked_feats = _split_picks(choices.picks, _choice_options(level_sources))
    features = list(dict.fromkeys([*leveled_feature_slugs(level_sources), *picked_features]))
    changes = _always_on_changes(features, loader)
    used_asi_slots: set[tuple[str, int]] = set()
    scores = _ability_scores(spec, choices, class_docs, background, used_asi_slots)
    feats = [
        *picked_feats,
        *_asi_level_feats(
            spec, choices, class_docs, used_asi_slots, {*features, *picked_feats}, loader
        ),
    ]
    modifiers = {name: ability_modifier(score) for name, score in scores.items()}
    pb = proficiency_bonus(spec.level)
    grants = proficiency_grants(
        [
            *(
                (class_docs[slug], level, "primary" if index == 0 else "secondary")
                for index, (slug, level) in enumerate(spec.classes.items())
            ),
            (subclass, subclass_level, None),
            (species, spec.level, None),
        ]
    )
    training = grants.armor | armor_training_from_changes(changes)
    worn = _worn(spec, loader, training)
    mode = _ac_mode(spec.ac_calc_mode, changes, modifiers, worn)
    skills, expertise = _skills(grants, background, choices)
    jack = has_flag(changes, "flags.dnd5e.jackOfAllTrades")
    die_sizes = {slug: hit_die_size(str(cls.hit_die)) for slug, cls in class_docs.items()}
    walk = species.movement.walk or 30
    passive = interpret_passive_stats(
        changes=changes,
        trait_grants=species.trait_grants,
        species_senses=species.senses,
        species_base_speed=walk,
    )
    if passive.skipped_keys:
        _log.debug(
            "derive_sheet: skipped non-allowlisted passive keys",
            extra={"skipped_keys": passive.skipped_keys},
        )
    return DerivedSheet(
        ability_scores=AbilityScores(**scores),
        ability_modifiers=modifiers,
        proficiency_bonus=pb,
        base_speed=(
            walk + passive.walk_speed_bonus - armor_speed_penalty(worn.body, scores["strength"])
        ),
        movement_modes=passive.movement_modes,
        senses=passive.senses,
        damage_resistances=passive.resistances,
        damage_immunities=passive.immunities,
        condition_immunities=passive.condition_immunities,
        save_proficiencies=grants.saves,
        skill_proficiencies=skills,
        skill_expertise=expertise,
        weapon_proficiencies=grants.weapons | weapon_proficiencies_from_changes(changes),
        armor_training=training,
        passive_perception=passive_perception(
            scores["wisdom"],
            "perception" in skills,
            pb,
            expertise="perception" in expertise,
            jack_of_all_trades=jack,
        ),
        jack_of_all_trades=jack,
        reliable_talent=has_flag(changes, "flags.dnd5e.reliableTalent"),
        stealth_disadvantage=bool(worn.body and worn.body.stealth_disadvantage),
        extra_attack_count=extra_attack_count(features),
        features=tuple(features),
        feats=tuple(feats),
        spell_slots=derive_multiclass_slots(spec.classes, loader=loader),
        pact_slots=derive_multiclass_pact_slots(spec.classes, loader=loader),
        hp_max=_hit_points(spec, die_sizes, modifiers["constitution"], changes),
        hit_dice=hit_dice_pool(spec.classes, die_sizes),
        ac=armor_class(
            mode,
            modifiers,
            body_armor=worn.body,
            body_armor_bonus=worn.body_bonus,
            shield_bonus=worn.shield_bonus,
        ),
        ac_calc_mode=mode,
    )


__all__ = [
    "AbilityScores",
    "CharacterBuildSpec",
    "CombatInstance",
    "DerivedSheet",
    "derive_multiclass_pact_slots",
    "derive_multiclass_slots",
    "derive_sheet",
    "derive_spell_slots",
    "make_build_spec",
]
