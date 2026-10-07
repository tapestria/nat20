"""The ``CharacterBuildSpec.selected_choices`` token grammar.

Pure parsing: tokens become typed picks, and ``build_spec.derive_sheet`` checks
them against the dataset. One token per choice:

* ``skill:<skill>`` — a chosen skill proficiency (long-form slug; spaces and
  hyphens become ``_``);
* ``expertise:<skill>`` — an Expertise pick;
* ``background:<ability>+<n>[,<ability>+<n>...]`` — the background's
  ability adjustment;
* ``asi:<class>:<level>:<ability>+<n>[,...]`` — the Ability Score
  Improvement feat taken at that class's level;
* ``feat:<class>:<level>:<feat>`` — another feat taken at that level;
* ``magic-initiate:<list>:<ability>:<cantrip>,<cantrip>:<spell>`` — one Magic
  Initiate's choices: the Cleric, Druid or Wizard list, its spellcasting
  ability (Intelligence, Wisdom or Charisma), two cantrips and a level 1 spell;
* ``<slug>`` — a pick from a class, subclass or species feature-choice pool.

Abilities are long names or 3-letter codes.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Literal, cast, get_args

from dnd5e_engine.events import Ability
from dnd5e_engine.rules.character import ABILITY_NAME_BY_CODE, AbilityName
from dnd5e_engine.rules.skills import SKILL_ABILITIES, Skill
from dnd5e_engine.types.combat import SpellcastingAbility

_ABILITY_NAMES: Final[frozenset[str]] = frozenset(ABILITY_NAME_BY_CODE.values())
_INCREASE: Final = re.compile(r"^([a-z]+)\+(\d+)$")
_SLUG: Final = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_ABILITY_CODES: Final[dict[str, str]] = {name: code for code, name in ABILITY_NAME_BY_CODE.items()}

# SRD 5.2 Magic Initiate: "two cantrips of your choice from the Cleric, Druid,
# or Wizard spell list. Intelligence, Wisdom, or Charisma is your spellcasting
# ability for this feat's spells".
MagicInitiateList = Literal["cleric", "druid", "wizard"]
_MAGIC_INITIATE_LISTS: Final[frozenset[str]] = frozenset(get_args(MagicInitiateList))
_MAGIC_INITIATE_ABILITIES: Final[frozenset[str]] = frozenset(get_args(SpellcastingAbility))


@dataclass(frozen=True)
class AsiPick:
    class_slug: str
    level: int
    increases: dict[AbilityName, int]


@dataclass(frozen=True)
class FeatPick:
    class_slug: str
    level: int
    feat_slug: str


@dataclass(frozen=True)
class MagicInitiatePick:
    spell_list: MagicInitiateList
    ability: SpellcastingAbility
    cantrips: tuple[str, str]
    spell: str


@dataclass(frozen=True)
class ParsedChoices:
    skills: tuple[Skill, ...] = ()
    expertise: tuple[Skill, ...] = ()
    background: dict[AbilityName, int] | None = None
    asis: tuple[AsiPick, ...] = ()
    feats: tuple[FeatPick, ...] = ()
    picks: tuple[str, ...] = ()
    magic_initiate: tuple[MagicInitiatePick, ...] = ()


def _skill(raw: str, token: str) -> Skill:
    slug = raw.strip().lower().replace(" ", "_").replace("-", "_")
    if slug not in SKILL_ABILITIES:
        raise ValueError(f"selected_choices token {token!r}: unknown skill {raw!r}")
    return cast(Skill, slug)


def _increases(raw: str, token: str) -> dict[AbilityName, int]:
    increases: dict[AbilityName, int] = {}
    for part in raw.split(","):
        match = _INCREASE.match(part.strip().lower())
        if match is None:
            raise ValueError(
                f"selected_choices token {token!r}: expected <ability>+<n>, got {part!r}"
            )
        code = match.group(1)
        name = ABILITY_NAME_BY_CODE.get(cast(Ability, code), code)
        if name not in _ABILITY_NAMES:
            raise ValueError(f"selected_choices token {token!r}: unknown ability {code!r}")
        ability = cast(AbilityName, name)
        if ability in increases:
            raise ValueError(f"selected_choices token {token!r} names {ability} twice")
        increases[ability] = int(match.group(2))
    return increases


def _slot(parts: list[str], token: str) -> tuple[str, int]:
    class_slug, level = parts[1], parts[2]
    if not _SLUG.match(class_slug) or not level.isdigit():
        raise ValueError(f"selected_choices token {token!r}: expected <class>:<level>")
    return class_slug, int(level)


def _magic_initiate(token: str) -> MagicInitiatePick:
    parts = token.split(":")
    if len(parts) != 5:
        raise ValueError(
            f"selected_choices token {token!r}: expected "
            "magic-initiate:<list>:<ability>:<cantrip>,<cantrip>:<spell>"
        )
    _, spell_list, ability, cantrips, spell = parts
    if spell_list not in _MAGIC_INITIATE_LISTS:
        raise ValueError(
            f"selected_choices token {token!r}: the spell list is cleric, druid or "
            f"wizard, not {spell_list!r}"
        )
    code = _ABILITY_CODES.get(ability.lower(), ability.lower())
    if code not in _MAGIC_INITIATE_ABILITIES:
        raise ValueError(
            f"selected_choices token {token!r}: the spellcasting ability is "
            f"Intelligence, Wisdom or Charisma, not {ability!r}"
        )
    chosen = cantrips.split(",")
    if len(chosen) != 2 or chosen[0] == chosen[1] or not all(map(_SLUG.match, chosen)):
        raise ValueError(f"selected_choices token {token!r}: expected two different cantrips")
    if not _SLUG.match(spell):
        raise ValueError(f"selected_choices token {token!r}: {spell!r} is not a spell slug")
    return MagicInitiatePick(
        cast(MagicInitiateList, spell_list),
        cast(SpellcastingAbility, code),
        (chosen[0], chosen[1]),
        spell,
    )


def parse_selected_choices(tokens: Sequence[str]) -> ParsedChoices:
    """Parse ``selected_choices`` into typed picks. ``ValueError`` for a malformed
    or repeated token; checks against the character's classes, background and
    pools happen in ``derive_sheet``."""
    skills: list[Skill] = []
    expertise: list[Skill] = []
    asis: list[AsiPick] = []
    feats: list[FeatPick] = []
    picks: list[str] = []
    magic_initiate: list[MagicInitiatePick] = []
    background: dict[AbilityName, int] | None = None
    for token in tokens:
        kind, sep, rest = token.partition(":")
        if not sep:
            if not _SLUG.match(token):
                raise ValueError(f"selected_choices token {token!r} is not a known kind or a slug")
            picks.append(token)
        elif kind == "skill":
            skills.append(_skill(rest, token))
        elif kind == "expertise":
            expertise.append(_skill(rest, token))
        elif kind == "background":
            if background is not None:
                raise ValueError(f"selected_choices token {token!r}: more than one background")
            background = _increases(rest, token)
        elif kind in ("asi", "feat"):
            parts = token.split(":")
            if len(parts) != 4:
                raise ValueError(
                    f"selected_choices token {token!r}: expected {kind}:<class>:<level>:<...>"
                )
            class_slug, level = _slot(parts, token)
            if kind == "asi":
                asis.append(AsiPick(class_slug, level, _increases(parts[3], token)))
            elif not _SLUG.match(parts[3]):
                raise ValueError(
                    f"selected_choices token {token!r}: {parts[3]!r} is not a feat slug"
                )
            else:
                feats.append(FeatPick(class_slug, level, parts[3]))
        elif kind == "magic-initiate":
            magic_initiate.append(_magic_initiate(token))
        else:
            raise ValueError(f"selected_choices token {token!r}: unknown kind {kind!r}")
    # SRD 5.2 Magic Initiate, Repeatable: "you must choose a different spell
    # list each time". A spell is chosen once across them: the engine casts each
    # spell with one ability.
    checks: list[tuple[str, Sequence[str]]] = [
        ("tokens", list(tokens)),
        ("skill picks", skills),
        ("expertise picks", expertise),
        ("Magic Initiate spell lists", [pick.spell_list for pick in magic_initiate]),
        (
            "Magic Initiate spells",
            [s for pick in magic_initiate for s in (*pick.cantrips, pick.spell)],
        ),
    ]
    for label, values in checks:
        repeated = sorted({v for v in values if values.count(v) > 1})
        if repeated:
            raise ValueError(f"selected_choices repeats {label}: {repeated}")
    return ParsedChoices(
        tuple(skills),
        tuple(expertise),
        background,
        tuple(asis),
        tuple(feats),
        tuple(picks),
        tuple(magic_initiate),
    )


__all__ = [
    "AsiPick",
    "FeatPick",
    "MagicInitiateList",
    "MagicInitiatePick",
    "ParsedChoices",
    "parse_selected_choices",
]
