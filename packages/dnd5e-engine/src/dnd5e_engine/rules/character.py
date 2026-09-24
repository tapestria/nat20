"""Pure SRD 5.2 character-derivation rules.

Zero I/O and no host imports: ``build_spec.derive_sheet`` fetches the dataset
documents through its loader and passes them in. Ground truth is the SRD 5.2
text in ``content24/chapter-2/character-creation.yml`` (Character Creation,
Level Advancement, Multiclassing) and ``content24/chapter-6/equipment.yml``
(Armor), with Foundry's ``config.mjs`` ``armorClasses`` table as the formula
reference.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING, Final, Literal

from dnd5e_srd_data.schema.advancement import AdvancementType

from dnd5e_engine.events import Ability

if TYPE_CHECKING:
    from dnd5e_srd_data.schema.class_ import Class, Subclass
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


def leveled_feature_slugs(
    sources: Sequence[tuple[Class | Subclass | Species | None, int]],
) -> list[str]:
    """Feature slugs each source grants at or below ITS OWN level.

    SRD 5.2 Multiclassing: "When you gain a new level in a class, you get its
    features for that level" — a Fighter 1 / Wizard 4 has the Fighter's level-1
    features only. Source order is kept, duplicates dropped, ``None`` skipped.
    """
    slugs: list[str] = []
    seen: set[str] = set()
    for source, level in sources:
        if source is None:
            continue
        for grant in source.granted_features:
            if grant.ref_type == "feature" and grant.level <= level and grant.slug not in seen:
                seen.add(grant.slug)
                slugs.append(grant.slug)
    return slugs


def granted_feature_slugs(
    sources: Sequence[Class | Subclass | Species | None], *, level: int
) -> list[str]:
    """Feature slugs ``sources`` grant at or below one shared ``level``.

    The live combat path's projection: a ``Combatant`` carries one class and its
    total level (BACKLOG.md, live multiclass). Shared by the USE_FEATURE
    repertoire gate, ``build_scale_values`` and the condition-immunity fold.
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


__all__ = [
    "ABILITY_NAME_BY_CODE",
    "EXTRA_ATTACK_TIERS",
    "FOUNDRY_AC_CALC",
    "AbilityName",
    "AbilityScoreMethod",
    "AcCalcMode",
    "HpMode",
    "extra_attack_count",
    "granted_feature_slugs",
    "leveled_feature_slugs",
    "subclass_gate_level",
]
