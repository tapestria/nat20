"""Corpus prose integrity — catch unsubstituted templates and broken enrichers.

Canonical descriptions are shipped product: hosts render them, and the engine
*parses* some of them (monster multiattack fan-out reads ``[[/item …]]`` tokens
out of prose). A description carrying an unsubstituted template placeholder is
therefore both a display bug and a resolution bug, and nothing else in the suite
looks for one.

This does not attempt to strip Foundry enricher markup wholesale — several
enrichers are load-bearing. It fails only on markup that is structurally broken.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

CANONICAL = Path(__file__).resolve().parents[1] / "src" / "dnd5e_srd_data" / "canonical"
#: Entries whose broken markup comes from upstream, not from our translator.
#: Each carries a note explaining the defect and when to re-check it. Hand-
#: editing ``canonical/`` is not an option -- it is translator output -- so the
#: defect is registered here and tracked in BACKLOG.md instead of hidden.
KNOWN_DEFECTS_FILE = (
    Path(__file__).resolve().parents[1] / "tests" / "oracle" / ("known_prose_defects.json")
)

#: Structurally broken markup: a template placeholder that survived translation,
#: or an enricher with no argument at all.
BROKEN_MARKUP = re.compile(
    r"""
      \{count\}            # unsubstituted count placeholder
    | \{name\}             # unsubstituted name placeholder
    | \[\[/item\s*\]\]     # item enricher with no target
    | \[\[/\s*\]\]         # empty enricher
    """,
    re.VERBOSE,
)


def _iter_descriptions(entry: Any, path: str = "") -> Iterator[tuple[str, str]]:
    """Yield ``(json path, text)`` for every ``description`` string in an entry."""
    if isinstance(entry, dict):
        for key, value in entry.items():
            here = f"{path}.{key}" if path else key
            if key == "description" and isinstance(value, str):
                yield here, value
            else:
                yield from _iter_descriptions(value, here)
    elif isinstance(entry, list):
        for index, value in enumerate(entry):
            yield from _iter_descriptions(value, f"{path}[{index}]")


CATEGORIES = sorted(p.name for p in CANONICAL.iterdir() if p.is_dir())


def _known_defects() -> dict[str, dict[str, object]]:
    if not KNOWN_DEFECTS_FILE.is_file():
        return {}
    return json.loads(KNOWN_DEFECTS_FILE.read_text(encoding="utf-8"))


@pytest.mark.parametrize("category", CATEGORIES)
def test_no_unsubstituted_template_placeholders(category: str) -> None:
    known = _known_defects()
    offenders: list[str] = []
    for path in sorted((CANONICAL / category).glob("*.json")):
        entry = json.loads(path.read_text(encoding="utf-8"))
        allowed = known.get(f"{category}/{path.stem}", {})
        allowed_markup = set(allowed.get("markup", []))  # type: ignore[arg-type]
        for json_path, text in _iter_descriptions(entry):
            for match in BROKEN_MARKUP.finditer(text):
                if match.group(0) in allowed_markup:
                    continue
                offenders.append(f"{category}/{path.stem}:{json_path}: {match.group(0)!r}")
    assert not offenders, (
        "canonical prose contains unsubstituted template markup — the translator "
        "emitted a placeholder instead of content:\n" + "\n".join(offenders)
    )


def test_multiattack_descriptions_name_at_least_one_action() -> None:
    """A multiattack whose prose names nothing cannot fan out at all.

    The engine falls back to repeating one sibling, which is silently wrong for
    a heterogeneous multiattack — so an empty description is a corpus defect.
    """
    offenders: list[str] = []
    for path in sorted((CANONICAL / "monsters").glob("*.json")):
        monster = json.loads(path.read_text(encoding="utf-8"))
        for action in monster.get("actions", []):
            if action.get("slug") != "multiattack":
                continue
            description = (action.get("description") or "").strip()
            if not description:
                offenders.append(f"{path.stem}: empty multiattack description")
            elif "[[/item" not in description and "attack" not in description.lower():
                offenders.append(f"{path.stem}: names no action -- {description[:80]!r}")
    assert not offenders, "unusable multiattack descriptions:\n" + "\n".join(offenders)


def test_known_prose_defects_are_still_real() -> None:
    """A registered defect that upstream has fixed must be de-registered.

    Keeps the allowlist from silently accumulating stale entries.
    """
    stale: list[str] = []
    for key, record in _known_defects().items():
        category, _, slug = key.partition("/")
        path = CANONICAL / category / f"{slug}.json"
        assert path.is_file(), f"{key} is registered but no longer exists in the corpus"
        text = path.read_text(encoding="utf-8")
        if not any(markup in text for markup in record["markup"]):  # type: ignore[operator]
            stale.append(key)
    assert not stale, (
        "these entries are registered in known_prose_defects.json but are now "
        f"clean -- delete their entries: {stale}"
    )


def test_opaque_key_multiattacks_are_labelled() -> None:
    """C22-S06: the five multiattacks that reference siblings by opaque Foundry
    key now carry the sibling name as a ``{Label}`` (rule card C22 §6 table)."""
    expected = {
        "bandit-captain": {"Scimitar", "Pistol"},
        "doppelganger": {"Slam", "Unsettling Visage"},
        "chain-devil": {"Chain", "Conjure Infernal Chain"},
        "scout": {"Shortsword", "Longbow"},
        "ettin": {"Battleaxe", "Morningstar"},
    }
    for slug, labels in expected.items():
        blob = json.loads((CANONICAL / "monsters" / f"{slug}.json").read_text(encoding="utf-8"))
        multiattack = next(a for a in blob["actions"] if a["slug"] == "multiattack")
        found = set(
            re.findall(r"\[\[/item \.[A-Za-z0-9]+\]\]\{([^}]+)\}", multiattack["description"])
        )
        assert labels <= found, f"{slug}: {multiattack['description']!r}"
