"""Keeps ``docs/capabilities.md`` honest.

The capability matrix publishes hard counts ("108 of 339 spells resolve to
nothing"). A published number that drifts is worse than no number, so the counts
are recomputed from the shipped corpus here and compared against what the page
claims. Change the behaviour, and this test tells you which sentence to update.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

CAPABILITIES_MD = Path(__file__).resolve().parents[3] / "docs" / "capabilities.md"

#: Activity kinds the resolver actually turns into ``CombatEvent``s. A
#: ``utility`` activity counts only when it carries effect riders — mirrors
#: ``dnd5e_engine.activities.resolver.resolve_activity``.
MECHANICAL_KINDS = frozenset({"attack", "damage", "save", "heal", "check", "cast"})


def _resolves(activity: dict[str, Any]) -> bool:
    kind = activity.get("kind")
    if kind in MECHANICAL_KINDS:
        return True
    return kind == "utility" and bool(activity.get("effects"))


@pytest.fixture(scope="module")
def canonical_dir() -> Path:
    import dnd5e_srd_data

    return Path(dnd5e_srd_data.__file__).parent / "canonical"


@pytest.fixture(scope="module")
def spell_stats(canonical_dir: Path) -> dict[str, int]:
    total = inert = inert_concentration = 0
    for path in sorted((canonical_dir / "spells").glob("*.json")):
        spell = json.loads(path.read_text())
        total += 1
        if not any(_resolves(a) for a in spell.get("activities", [])):
            inert += 1
            if spell.get("concentration"):
                inert_concentration += 1
    return {
        "total": total,
        "inert": inert,
        "resolving": total - inert,
        "inert_concentration": inert_concentration,
    }


@pytest.fixture(scope="module")
def matrix_text() -> str:
    assert CAPABILITIES_MD.is_file(), f"missing {CAPABILITIES_MD}"
    return CAPABILITIES_MD.read_text()


def test_published_spell_counts_match_the_corpus(
    spell_stats: dict[str, int], matrix_text: str
) -> None:
    for label, key in (
        ("Spells in the corpus", "total"),
        ("Resolve to at least one mechanical activity", "resolving"),
        ("Load but resolve to nothing", "inert"),
    ):
        match = re.search(rf"{re.escape(label)}.*?\*\*(\d+)\*\*", matrix_text)
        assert match, f"capabilities.md no longer publishes a count for {label!r}"
        assert int(match.group(1)) == spell_stats[key], (
            f"capabilities.md says {match.group(1)} for {label!r}, corpus says {spell_stats[key]}"
        )

    conc = re.search(r"of which are concentration spells.*?\*\*(\d+)\*\*", matrix_text)
    assert conc, "capabilities.md no longer publishes the inert-concentration count"
    assert int(conc.group(1)) == spell_stats["inert_concentration"]


def test_named_inert_concentration_spells_really_are_inert(canonical_dir: Path) -> None:
    """The page names specific staples as inert; verify each actually is."""
    for slug in (
        "blur",
        "darkness",
        "fog-cloud",
        "spiritual-weapon",
        "wall-of-force",
        "silent-image",
        "globe-of-invulnerability",
        "expeditious-retreat",
    ):
        spell = json.loads((canonical_dir / "spells" / f"{slug}.json").read_text())
        assert spell.get("concentration"), f"{slug} is no longer a concentration spell"
        assert not any(_resolves(a) for a in spell.get("activities", [])), (
            f"{slug} now resolves — remove it from the inert list in capabilities.md"
        )


def test_published_legendary_action_count_matches_the_corpus(
    canonical_dir: Path, matrix_text: str
) -> None:
    with_legendary = sum(
        1
        for path in (canonical_dir / "monsters").glob("*.json")
        if json.loads(path.read_text()).get("legendary_actions")
    )
    match = re.search(r"(\d+) monsters carry them in the data", matrix_text)
    assert match, "capabilities.md no longer publishes the legendary-action count"
    assert int(match.group(1)) == with_legendary


def test_legendary_and_lair_actions_are_still_unconsumed() -> None:
    """If someone implements these, this test fails and the page must be updated."""
    import dnd5e_engine.activities.monster_actions as module

    source = Path(module.__file__).read_text()
    body = source.split('"""', 2)[-1]  # skip the module docstring
    for field in ("legendary_actions", "lair_actions", "special_abilities"):
        assert field not in body, (
            f"{field} is now read by the engine — update docs/capabilities.md "
            "and BACKLOG.md, then relax this test"
        )
