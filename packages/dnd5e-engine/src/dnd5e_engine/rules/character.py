"""Pure SRD 5.2 character-derivation rules.

Zero I/O and no host imports: ``build_spec.derive_sheet`` fetches the dataset
documents through its loader and passes them in. Ground truth is the SRD 5.2
text in ``content24/chapter-2/character-creation.yml`` (Character Creation,
Level Advancement, Multiclassing) and ``content24/chapter-6/equipment.yml``
(Armor), with Foundry's ``config.mjs`` ``armorClasses`` table as the formula
reference.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

from dnd5e_srd_data.schema.advancement import AdvancementType

from dnd5e_engine.events import Ability
from dnd5e_engine.rules.dice import STANDARD_ARRAY, validate_point_buy
from dnd5e_engine.rules.skills import SKILL_CODE_TO_SLUG, Skill

if TYPE_CHECKING:
    from dnd5e_srd_data.schema.advancement import AdvancementEntry
    from dnd5e_srd_data.schema.class_ import Class, Subclass
    from dnd5e_srd_data.schema.common import PassiveEffectChange
    from dnd5e_srd_data.schema.item import Armor
    from dnd5e_srd_data.schema.species import Species

AbilityName = Literal["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"]

ABILITY_NAME_BY_CODE: Final[dict[Ability, AbilityName]] = {
    "str": "strength",
    "dex": "dexterity",
    "con": "constitution",
    "int": "intelligence",
    "wis": "wisdom",
    "cha": "charisma",
}

# SRD 5.2 "Gaining a Level": after level 1, roll the Hit Die or take the fixed value.
HpMode = Literal["fixed", "rolled"]

# SRD 5.2 "Step 3: Ability Scores": the two methods whose results can be checked.
AbilityScoreMethod = Literal["standard_array", "point_buy"]

# Foundry ``armorClasses`` modes an SRD 5.2 character can reach; ``natural``,
# ``flat`` and ``custom`` have no SRD character source, and a host that needs
# one pins ``ac`` directly.
AcCalcMode = Literal[
    "default", "mage_armor", "unarmored_barbarian", "unarmored_monk", "unarmored_bard"
]

FOUNDRY_AC_CALC: Final[dict[str, AcCalcMode]] = {
    "default": "default",
    "mage": "mage_armor",
    "unarmoredBarb": "unarmored_barbarian",
    "unarmoredMonk": "unarmored_monk",
    "unarmoredBard": "unarmored_bard",
}

# (feature slug, extra attacks), highest tier first: tiers never add together.
EXTRA_ATTACK_TIERS: Final[tuple[tuple[str, int], ...]] = (
    ("three-extra-attacks", 3),
    ("two-extra-attacks", 2),
    ("extra-attack", 1),
)


def leveled_feature_levels(
    sources: Sequence[tuple[Class | Subclass | Species | None, int]],
) -> dict[str, int]:
    """Feature slug → the level of the first source granting it at or below
    that source's OWN level. SRD 5.2 Multiclassing: "When you gain a new level
    in a class, you get its features for that level" — and a feature's own
    ``@scale`` values read at that level. Source order is kept; ``None`` is
    skipped."""
    levels: dict[str, int] = {}
    for source, level in sources:
        if source is None:
            continue
        for grant in source.granted_features:
            if grant.ref_type == "feature" and grant.level <= level and grant.slug not in levels:
                levels[grant.slug] = level
    return levels


def leveled_feature_slugs(
    sources: Sequence[tuple[Class | Subclass | Species | None, int]],
) -> list[str]:
    """Feature slugs each source grants at or below ITS OWN level.

    SRD 5.2 Multiclassing: "When you gain a new level in a class, you get its
    features for that level" — a Fighter 1 / Wizard 4 has the Fighter's level-1
    features only. Source order is kept, duplicates dropped, ``None`` skipped.
    """
    return list(leveled_feature_levels(sources))


def granted_feature_slugs(
    sources: Sequence[Class | Subclass | Species | None], *, level: int
) -> list[str]:
    """Feature slugs ``sources`` grant at or below one shared ``level``.

    Every source read at one level — for a caller with no per-class levels.
    """
    return leveled_feature_slugs([(source, level) for source in sources])


def subclass_gate_level(cls: Class) -> int | None:
    """Class level of the class's ``Subclass`` advancement (3 for every SRD 5.2
    class), or ``None`` when the class has none."""
    for entry in cls.advancement:
        if entry.type == AdvancementType.SUBCLASS:
            return entry.level
    return None


def extra_attack_count(feature_slugs: Iterable[str]) -> int:
    """Extra attacks the Attack action grants (0 = none).

    SRD 5.2 Multiclassing, "Extra Attack": "If you gain the Extra Attack feature
    from more than one class, the features don't stack. You can't make more
    than two attacks with this feature unless you have a feature that says you
    can (such as the Fighter's Two Extra Attacks feature)."
    """
    owned = frozenset(feature_slugs)
    for slug, count in EXTRA_ATTACK_TIERS:
        if slug in owned:
            return count
    return 0


# SRD 5.2: "None of these increases can raise a score above 20."
MAX_SCORE_FROM_INCREASES: Final = 20


def ability_score_improvement(cls: Class, level: int) -> AdvancementEntry | None:
    """The class's player-choice ``AbilityScoreImprovement`` at exactly ``level``
    (``configuration.points > 0``). Fixed grants such as the Monk's level-20
    Body and Mind (``points == 0``) are not a choice."""
    for entry in cls.advancement:
        if (
            entry.type == AdvancementType.ABILITY_SCORE_IMPROVEMENT
            and entry.level == level
            and int(entry.configuration.get("points") or 0) > 0
        ):
            return entry
    return None


def validate_ability_score_method(
    scores: Mapping[AbilityName, int], method: AbilityScoreMethod
) -> None:
    """Prove the pre-adjustment scores came from ``method``: the Standard Array
    (15, 14, 13, 12, 10, 8 in any order) or Point Buy (scores 8-15, at most 27
    points by the Ability Score Point Costs table)."""
    values = [scores[name] for name in ABILITY_NAME_BY_CODE.values()]
    if method == "standard_array":
        if sorted(values) != sorted(STANDARD_ARRAY):
            raise ValueError(
                f"standard_array needs 15, 14, 13, 12, 10, 8 in any order; got {values}"
            )
        return
    ok, message = validate_point_buy(dict(scores.items()))
    if not ok:
        raise ValueError(f"point_buy: {message}")


def validate_increase_budget(
    increases: Mapping[AbilityName, int],
    *,
    allowed: Collection[AbilityName],
    points: int,
    cap: int,
    source: str,
) -> None:
    """An ability-increase choice spends exactly ``points``, at most ``cap`` per
    ability, on ``allowed`` abilities only (Foundry ``AbilityScoreImprovement``
    ``points``/``cap``/``locked``; ``Background.ability_options``)."""
    outside = sorted(set(increases) - set(allowed))
    if outside:
        raise ValueError(
            f"{source}: {outside} not among the abilities it can raise {sorted(allowed)}"
        )
    over = sorted(name for name, amount in increases.items() if not 1 <= amount <= cap)
    if over:
        raise ValueError(f"{source}: each increase must be 1-{cap}; {over} are not")
    spent = sum(increases.values())
    if spent != points:
        raise ValueError(f"{source}: must spend exactly {points} point(s); got {spent}")


def apply_ability_increases(
    scores: Mapping[AbilityName, int], increases: Mapping[AbilityName, int], *, source: str
) -> dict[AbilityName, int]:
    """Add ``increases`` to ``scores``; SRD 5.2 stops these increases at 20."""
    raised = dict(scores)
    for name, amount in increases.items():
        value = raised[name] + amount
        if value > MAX_SCORE_FROM_INCREASES:
            raise ValueError(
                f"{source} would raise {name} to {value}; these increases stop at "
                f"{MAX_SCORE_FROM_INCREASES}"
            )
        raised[name] = value
    return raised


_MODE_ADD: Final = 2
_HP_PER_LEVEL_KEY: Final = "system.attributes.hp.bonuses.level"
_HP_OVERALL_KEY: Final = "system.attributes.hp.bonuses.overall"
_CLASS_LEVELS_REF: Final = re.compile(r"^@classes\.([a-z0-9-]+)\.levels$")


def hit_die_size(hit_die: str) -> int:
    """``"d10"`` → 10 (``Class.hit_die`` is a ``HitDie`` StrEnum)."""
    return int(str(hit_die).removeprefix("d"))


def fixed_hit_points(die_size: int) -> int:
    """SRD 5.2 Fixed Hit Points by Class — Barbarian 7, Fighter/Paladin/Ranger 6,
    Bard/Cleric/Druid/Monk/Rogue/Warlock 5, Sorcerer/Wizard 4: half the die + 1."""
    return die_size // 2 + 1


def hit_points_max(
    classes: Mapping[str, int],
    die_sizes: Mapping[str, int],
    con_modifier: int,
    *,
    rolls: Mapping[str, Sequence[int]] | None = None,
) -> int:
    """SRD 5.2 Hit Point maximum for a single- or multiclass character.

    "Your class and Constitution modifier determine your Hit Point maximum at
    level 1"; later levels "Roll that die, add your Constitution modifier to the
    roll, and add the total (minimum of 1) ... Instead of rolling, you can use
    the fixed value shown in the Fixed Hit Points by Class table"; and "You gain
    the level 1 Hit Points for a class only when your total character level is 1".
    The FIRST key of ``classes`` is the class taken at level 1. With ``rolls``,
    every later level uses that class's recorded result in order: the first class
    records ``level - 1`` rolls, every other class ``level``. The current CON
    modifier applies to every level.
    """
    if rolls is not None:
        unknown = sorted(set(rolls) - set(classes))
        if unknown:
            raise ValueError(f"hp_rolls names classes not in classes: {unknown}")
    total = 0
    for index, (slug, level) in enumerate(classes.items()):
        die = die_sizes[slug]
        later = level - 1 if index == 0 else level
        if rolls is None:
            gains = [fixed_hit_points(die)] * later
        else:
            gains = list(rolls.get(slug, ()))
            if len(gains) != later:
                raise ValueError(f"hp_rolls[{slug!r}] needs {later} roll(s), got {len(gains)}")
            if any(not 1 <= gain <= die for gain in gains):
                raise ValueError(f"hp_rolls[{slug!r}] has results outside 1-{die}: {gains}")
        if index == 0:
            gains = [die, *gains]
        total += sum(max(1, gain + con_modifier) for gain in gains)
    return total


def hit_point_bonus(
    changes: Iterable[PassiveEffectChange], *, total_level: int, classes: Mapping[str, int]
) -> int:
    """Always-on HP bonuses: Foundry ``hp.bonuses.level`` adds its value once per
    character level (Dwarven Toughness), ``hp.bonuses.overall`` once (Draconic
    Resilience's ``@classes.sorcerer.levels``). Literal integers and that one
    reference are understood; other values are ignored, like every non-allowlisted
    passive value."""
    bonus = 0
    for change in changes:
        if change.mode != _MODE_ADD or change.key not in (_HP_PER_LEVEL_KEY, _HP_OVERALL_KEY):
            continue
        raw = change.value.strip().strip('"').strip()
        match = _CLASS_LEVELS_REF.match(raw)
        if match is not None:
            value = classes.get(match.group(1), 0)
        elif raw.lstrip("+-").isdigit():  # Foundry writes signed literals ("+1") too
            value = int(raw)
        else:
            continue
        bonus += value * total_level if change.key == _HP_PER_LEVEL_KEY else value
    return bonus


def hit_dice_pool(classes: Mapping[str, int], die_sizes: Mapping[str, int]) -> dict[int, int]:
    """SRD 5.2 Multiclassing: "Add together the Hit Dice granted by all your
    classes to form your pool of Hit Dice" — same-size dice pool, different
    sizes are tracked separately."""
    pool: dict[int, int] = {}
    for slug, level in classes.items():
        pool[die_sizes[slug]] = pool.get(die_sizes[slug], 0) + level
    return pool


# Foundry Trait ``classRestriction``: SRD 5.2 Multiclassing — "When you gain your
# first level in a class other than your initial class, you gain only some of
# the new class's starting proficiencies". "primary" entries apply only to the
# class taken at level 1, "secondary" only to a class multiclassed into.
ClassRole = Literal["primary", "secondary"]

ArmorTraining = Literal["light", "medium", "heavy", "shield"]

_ARMOR_TOKENS: Final[dict[str, ArmorTraining]] = {
    "lgt": "light",
    "med": "medium",
    "hvy": "heavy",
    "shl": "shield",
}
_WEAPON_CATEGORY_TOKENS: Final[dict[str, tuple[str, str]]] = {
    "sim": ("simple_melee", "simple_ranged"),
    "mar": ("martial_melee", "martial_ranged"),
}

# Foundry ``weaponIds`` keys whose corpus slug is hyphenated; every other key
# already equals its weapon's slug.
FOUNDRY_WEAPON_ID_TO_SLUG: Final[dict[str, str]] = {
    "handcrossbow": "hand-crossbow",
    "heavycrossbow": "heavy-crossbow",
    "lightcrossbow": "light-crossbow",
    "lighthammer": "light-hammer",
    "warpick": "war-pick",
}

_MODE_OVERRIDE: Final = 5
_WEAPON_PROF_KEY: Final = "system.traits.weaponProf.value"
_ARMOR_PROF_KEY: Final = "system.traits.armorProf.value"


@dataclass(frozen=True)
class ProficiencyGrants:
    saves: frozenset[Ability]
    skills: frozenset[Skill]
    weapons: frozenset[str]
    armor: frozenset[ArmorTraining]


def _weapon_tokens(token: str) -> tuple[str, ...]:
    parts = token.split(":")
    if len(parts) == 2:
        return _WEAPON_CATEGORY_TOKENS.get(parts[1], ())
    if len(parts) == 3 and parts[2] != "*":
        return (FOUNDRY_WEAPON_ID_TO_SLUG.get(parts[2], parts[2]),)
    return ()


def proficiency_grants(
    sources: Sequence[tuple[Class | Subclass | Species | None, int, ClassRole | None]],
) -> ProficiencyGrants:
    """Fixed save, skill, weapon and armor proficiencies from the sources'
    ``Trait`` advancements at or below each source's level. Only ``mode ==
    "default"`` entries grant proficiency; choice pools are the host's picks."""
    saves: set[Ability] = set()
    skills: set[Skill] = set()
    weapons: set[str] = set()
    armor: set[ArmorTraining] = set()
    for source, level, role in sources:
        if source is None:
            continue
        for entry in source.advancement:
            if entry.type != AdvancementType.TRAIT or entry.level > level:
                continue
            if entry.class_restriction and entry.class_restriction != role:
                continue
            if entry.configuration.get("mode", "default") != "default":
                continue
            for token in entry.configuration.get("grants") or ():
                kind, _, rest = str(token).partition(":")
                if kind == "saves" and rest in ABILITY_NAME_BY_CODE:
                    saves.add(rest)
                elif kind == "skills" and rest in SKILL_CODE_TO_SLUG:
                    skills.add(SKILL_CODE_TO_SLUG[rest])
                elif kind == "weapon":
                    weapons.update(_weapon_tokens(str(token)))
                elif kind == "armor" and rest in _ARMOR_TOKENS:
                    armor.add(_ARMOR_TOKENS[rest])
    return ProficiencyGrants(
        frozenset(saves), frozenset(skills), frozenset(weapons), frozenset(armor)
    )


def _values(changes: Iterable[PassiveEffectChange], key: str) -> list[str]:
    return [
        c.value.strip().strip('"').strip() for c in changes if c.key == key and c.mode == _MODE_ADD
    ]


def weapon_proficiencies_from_changes(changes: Iterable[PassiveEffectChange]) -> frozenset[str]:
    """Weapon categories always-on features add (Divine Order: Protector,
    Primal Order Warden → ``"mar"``)."""
    return frozenset(
        w
        for value in _values(changes, _WEAPON_PROF_KEY)
        for w in _WEAPON_CATEGORY_TOKENS.get(value, ())
    )


def armor_training_from_changes(changes: Iterable[PassiveEffectChange]) -> frozenset[ArmorTraining]:
    """Armor training always-on features add (Protector → heavy, Warden → medium)."""
    return frozenset(
        _ARMOR_TOKENS[v] for v in _values(changes, _ARMOR_PROF_KEY) if v in _ARMOR_TOKENS
    )


def has_flag(changes: Iterable[PassiveEffectChange], key: str) -> bool:
    """True when an always-on override sets the Foundry character flag ``key``
    (``flags.dnd5e.jackOfAllTrades``, ``flags.dnd5e.reliableTalent``)."""
    return any(
        c.key == key and c.mode == _MODE_OVERRIDE and c.value.strip().strip('"').lower() == "true"
        for c in changes
    )


# SRD 5.2: "A creature can have Attunement with no more than three magic items at a time."
MAX_ATTUNED_ITEMS: Final = 3

_ATTUNEMENT_MAX_KEY: Final = "system.attributes.attunement.max"


def attunement_limit(changes: Iterable[PassiveEffectChange]) -> int:
    """The build's attunement limit: the SRD 5.2 base of three, plus every
    literal-int ADD change on ``system.attributes.attunement.max``. The
    Thief's Use Magic Device (rogue level 13) grants one such change
    (``mode`` ``_MODE_ADD``, value ``"1"``): its own corpus description
    says "You can attune to up to four magic items at once." A build
    without such a feature keeps the base of three."""
    values = _values(changes, _ATTUNEMENT_MAX_KEY)
    return MAX_ATTUNED_ITEMS + sum(int(v) for v in values if v.lstrip("+-").isdigit())


_AC_CALC_KEY: Final = "system.attributes.ac.calc"


def ac_modes_from_changes(changes: Iterable[PassiveEffectChange]) -> frozenset[AcCalcMode]:
    """``"default"`` plus every mode an always-on feature offers (Unarmored
    Defense, Draconic Resilience) through a ``system.attributes.ac.calc`` override."""
    modes: set[AcCalcMode] = {"default"}
    for change in changes:
        if change.key == _AC_CALC_KEY and change.mode == _MODE_OVERRIDE:
            mode = FOUNDRY_AC_CALC.get(change.value.strip().strip('"'))
            if mode is not None:
                modes.add(mode)
    return frozenset(modes)


def ac_mode_eligible(mode: AcCalcMode, *, wearing_armor: bool, wielding_shield: bool) -> bool:
    """SRD 5.2 gates every alternative mode on what is worn — Unarmored Defense
    (Barbarian) "While you aren't wearing any armor ... You can use a Shield and
    still gain this benefit", Unarmored Defense (Monk) "While you aren't wearing
    armor or wielding a Shield", Draconic Resilience "While you aren't wearing
    armor", Mage Armor "a willing creature who isn't wearing armor ... The spell
    ends early if the target dons armor". Foundry leaves these gates to the
    player; the engine applies them."""
    if mode == "default":
        return True
    if wearing_armor:
        return False
    return not (mode == "unarmored_monk" and wielding_shield)


def armor_class(
    mode: AcCalcMode,
    modifiers: Mapping[AbilityName, int],
    *,
    body_armor: Armor | None,
    body_armor_bonus: int,
    shield_bonus: int,
) -> int:
    """AC under one mode (Foundry ``armorClasses``), plus the Shield in every
    mode as Foundry's ``ac.shield`` is. ``default`` is 10 + DEX unarmored, else
    the armor's AC with DEX capped at its maximum and ignored in heavy armor
    ("your AC is 16 in Chain Mail")."""
    dex = modifiers["dexterity"]
    if mode == "mage_armor":
        base = 13 + dex
    elif mode == "unarmored_barbarian":
        base = 10 + dex + modifiers["constitution"]
    elif mode == "unarmored_monk":
        base = 10 + dex + modifiers["wisdom"]
    elif mode == "unarmored_bard":
        base = 10 + dex + modifiers["charisma"]
    elif body_armor is None:
        base = 10 + dex
    else:
        if body_armor.armor_category == "heavy":
            dex_contribution = 0
        elif body_armor.dex_bonus_max is None:
            dex_contribution = dex
        else:
            dex_contribution = min(dex, body_armor.dex_bonus_max)
        base = body_armor.base_ac + dex_contribution + body_armor_bonus
    return base + shield_bonus


def armor_speed_penalty(body_armor: Armor | None, strength: int) -> int:
    """SRD 5.2 armor Strength column: the armor "reduces the wearer's speed by
    10 feet unless the wearer has a Strength score equal to or higher than the
    listed score"."""
    if body_armor is None or body_armor.strength_min is None:
        return 0
    return 10 if strength < body_armor.strength_min else 0


__all__ = [
    "ABILITY_NAME_BY_CODE",
    "EXTRA_ATTACK_TIERS",
    "FOUNDRY_AC_CALC",
    "FOUNDRY_WEAPON_ID_TO_SLUG",
    "MAX_ATTUNED_ITEMS",
    "MAX_SCORE_FROM_INCREASES",
    "AbilityName",
    "AbilityScoreMethod",
    "AcCalcMode",
    "ArmorTraining",
    "ClassRole",
    "HpMode",
    "ProficiencyGrants",
    "ability_score_improvement",
    "ac_mode_eligible",
    "ac_modes_from_changes",
    "apply_ability_increases",
    "armor_class",
    "armor_speed_penalty",
    "armor_training_from_changes",
    "attunement_limit",
    "extra_attack_count",
    "fixed_hit_points",
    "granted_feature_slugs",
    "has_flag",
    "hit_dice_pool",
    "hit_die_size",
    "hit_point_bonus",
    "hit_points_max",
    "leveled_feature_levels",
    "leveled_feature_slugs",
    "proficiency_grants",
    "subclass_gate_level",
    "validate_ability_score_method",
    "validate_increase_budget",
    "weapon_proficiencies_from_changes",
]
