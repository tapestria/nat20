"""Coverage floors for the SRD oracle.

``test_canonical_against_oracle.py`` compares canonical entries against the
oracle *only for slugs the oracle contains* — a slug with no oracle entry is
silently skipped. That is the right behaviour for the comparison, but it means
the whole fidelity suite can report green while covering almost nothing.

These floors make oracle coverage itself a tested property, so a shrinking
oracle fails loudly instead of quietly weakening the gate.

The monster floor is deliberately low: the monster oracle currently holds only a
handful of entries against 341 canonical monsters. That gap is tracked in
``BACKLOG.md``. The floor exists to stop it getting *worse* and to be ratcheted
up as entries are added — raise it, never lower it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ORACLE_DIR = ROOT / "tests" / "oracle"
CANONICAL = ROOT / "src" / "dnd5e_srd_data" / "canonical"

#: category -> (oracle filename, minimum fraction of canonical slugs covered).
#: Ratchet upward as oracle entries are added; never lower a floor.
COVERAGE_FLOORS: dict[str, tuple[str, float]] = {
    # Well covered — these floors sit just under today's real numbers.
    "spells": ("srd_spell_oracle.json", 0.90),  # 93.2%
    "items": ("srd_item_oracle.json", 0.75),  # 75.3%
    "species": ("srd_species_oracle.json", 1.00),
    "backgrounds": ("srd_background_oracle.json", 1.00),
    "feats": ("srd_feat_oracle.json", 1.00),
    "classes": ("srd_class_oracle.json", 1.00),
    # Known-thin. Both are tracked in BACKLOG.md; the floors pin today's
    # baseline so coverage cannot regress while the gap is being closed.
    "subclasses": ("srd_subclass_oracle.json", 0.30),  # 33.3%
    "monsters": ("srd_monster_oracle.json", 0.008),  # 0.9% — 3 of 341
}


def _canonical_slugs(category: str) -> set[str]:
    return {p.stem for p in (CANONICAL / category).glob("*.json")}


#: Slug-alias maps the fidelity suite honours when matching canonical -> oracle.
ALIAS_FILES: dict[str, str] = {
    "spells": "slug_aliases.json",
    "monsters": "monster_form_aliases.json",
    "subclasses": "subclass_aliases.json",
}


def _oracle_keys(filename: str) -> set[str]:
    path = ORACLE_DIR / filename
    if not path.is_file():
        return set()
    return set(json.loads(path.read_text(encoding="utf-8")))


def _aliases(category: str) -> dict[str, str]:
    filename = ALIAS_FILES.get(category)
    if filename is None:
        return {}
    path = ORACLE_DIR / filename
    if not path.is_file():
        return {}
    loaded = json.loads(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def _covered(category: str, filename: str) -> set[str]:
    """Canonical slugs the oracle can match, honouring the alias maps."""
    canonical = _canonical_slugs(category)
    keys = _oracle_keys(filename)
    alias = _aliases(category)
    return {slug for slug in canonical if slug in keys or alias.get(slug) in keys}


@pytest.mark.parametrize(
    ("category", "filename", "floor"),
    [(cat, fn, floor) for cat, (fn, floor) in COVERAGE_FLOORS.items()],
)
def test_oracle_covers_enough_of_the_corpus(category: str, filename: str, floor: float) -> None:
    canonical = _canonical_slugs(category)
    assert canonical, f"no canonical entries found for {category}"
    covered = _covered(category, filename)
    ratio = len(covered) / len(canonical)
    assert ratio >= floor, (
        f"{category}: oracle covers {len(covered)}/{len(canonical)} "
        f"({ratio:.1%}), below the {floor:.1%} floor. The fidelity suite passes "
        f"vacuously for uncovered slugs — add oracle entries rather than "
        f"lowering this floor."
    )


def test_monster_oracle_coverage_is_reported_honestly() -> None:
    """Documents the current monster-oracle gap as an explicit, visible number.

    This is not a pass/fail quality bar — it exists so the shortfall shows up in
    test output instead of hiding behind a green fidelity suite.
    """
    canonical = _canonical_slugs("monsters")
    covered = _covered("monsters", "srd_monster_oracle.json")
    uncovered = len(canonical) - len(covered)
    assert uncovered >= 0
    # A tripwire: if someone materially expands the oracle, tighten the floor
    # in COVERAGE_FLOORS to lock the improvement in.
    if len(covered) > 40:  # pragma: no cover - fires only after real expansion
        pytest.fail(
            f"monster oracle now covers {len(covered)}/{len(canonical)} — raise "
            "the 'monsters' floor in COVERAGE_FLOORS to lock this in."
        )
