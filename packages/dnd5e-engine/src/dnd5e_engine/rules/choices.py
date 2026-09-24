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
* ``<slug>`` — a pick from a class, subclass or species feature-choice pool.

Abilities are long names or 3-letter codes.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, cast

from dnd5e_engine.events import Ability
from dnd5e_engine.rules.character import ABILITY_NAME_BY_CODE, AbilityName
from dnd5e_engine.rules.skills import SKILL_ABILITIES, Skill

_ABILITY_NAMES: Final[frozenset[str]] = frozenset(ABILITY_NAME_BY_CODE.values())
_INCREASE: Final = re.compile(r"^([a-z]+)\+(\d+)$")
_SLUG: Final = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


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
class ParsedChoices:
    skills: tuple[Skill, ...] = ()
    expertise: tuple[Skill, ...] = ()
    background: dict[AbilityName, int] | None = None
    asis: tuple[AsiPick, ...] = ()
    feats: tuple[FeatPick, ...] = ()
    picks: tuple[str, ...] = ()


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


def parse_selected_choices(tokens: Sequence[str]) -> ParsedChoices:
    """Parse ``selected_choices`` into typed picks. ``ValueError`` for a malformed
    or repeated token; checks against the character's classes, background and
    pools happen in ``derive_sheet``."""
    skills: list[Skill] = []
    expertise: list[Skill] = []
    asis: list[AsiPick] = []
    feats: list[FeatPick] = []
    picks: list[str] = []
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
        else:
            raise ValueError(f"selected_choices token {token!r}: unknown kind {kind!r}")
    checks: list[tuple[str, Sequence[str]]] = [
        ("tokens", list(tokens)),
        ("skill picks", skills),
        ("expertise picks", expertise),
    ]
    for label, values in checks:
        repeated = sorted({v for v in values if values.count(v) > 1})
        if repeated:
            raise ValueError(f"selected_choices repeats {label}: {repeated}")
    return ParsedChoices(
        tuple(skills), tuple(expertise), background, tuple(asis), tuple(feats), tuple(picks)
    )


__all__ = ["AsiPick", "FeatPick", "ParsedChoices", "parse_selected_choices"]
