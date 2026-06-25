"""Derive canonical→oracle slug aliases from word-transposition matches.

Foundry naming uses English word order (`light-crossbow`, `studded-leather`);
5e-bits uses SRD reference-table convention (`crossbow-light`, `leather-studded`).
We walk the unmatched canonical and oracle sets and find unique
single-word-transposition matches programmatically — those are added to
``tests/oracle/slug_aliases.json``.

Heuristics applied (in order):
1. Exact word-set equality after splitting on hyphen — if the canonical slug's
   word multiset equals an oracle slug's word multiset, alias them. (Catches
   `light-crossbow` ↔ `crossbow-light`.)
2. Canonical slug + a trailing form/qualifier (e.g. ``-flask``, ``-vial``,
   ``-bottle``) found in the oracle. (Catches ``alchemists-fire`` ↔
   ``alchemists-fire-flask``.)

We refuse to alias when more than one oracle slug matches a canonical — we want
unambiguous mappings only. Manual entries can be added afterward by hand.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ORACLE = ROOT / "tests" / "oracle" / "srd_item_oracle.json"
CANONICAL_DIR = ROOT / "src" / "dnd5e_srd_data" / "canonical" / "items"
OUT = ROOT / "tests" / "oracle" / "slug_aliases.json"

_FORM_SUFFIXES = ("flask", "vial", "bottle", "jug", "pot", "bag", "pouch")


def _canon_slugs() -> set[str]:
    return {p.stem for p in CANONICAL_DIR.glob("*.json")}


def main() -> int:
    oracle = json.loads(ORACLE.read_text(encoding="utf-8"))
    canonical = _canon_slugs()
    oracle_set = set(oracle.keys())

    unmatched_canon = sorted(canonical - oracle_set)
    unmatched_oracle = sorted(oracle_set - canonical)

    # Build oracle word-multiset index (frozenset of (word, count) so duplicates
    # are tracked).
    def words(slug: str) -> tuple[str, ...]:
        return tuple(sorted(slug.split("-")))

    oracle_by_words: dict[tuple[str, ...], list[str]] = {}
    for s in unmatched_oracle:
        oracle_by_words.setdefault(words(s), []).append(s)

    aliases: dict[str, str] = {}

    # Rule 3 needs the unmatched oracle set indexed by word-subset containment.
    oracle_word_sets: dict[str, set[str]] = {s: set(s.split("-")) for s in unmatched_oracle}

    for canon in unmatched_canon:
        cw = words(canon)
        # Rule 1: exact word-multiset match — unambiguous transposition.
        matches = oracle_by_words.get(cw, [])
        if len(matches) == 1:
            aliases[canon] = matches[0]
            continue
        # Rule 2: canonical + form-suffix match.
        matched_by_suffix = False
        for suffix in _FORM_SUFFIXES:
            candidate = f"{canon}-{suffix}"
            if candidate in oracle_set:
                aliases[canon] = candidate
                matched_by_suffix = True
                break
        if matched_by_suffix:
            continue
        # Rule 3: oracle slug contains every word of canonical as a subset, AND
        # the match is unique. Catches:
        #   bag-of-sand          → little-bag-of-sand
        #   ball-bearings        → ball-bearings-bag-of-1000
        #   chalk                → chalk-1-piece
        #   basic-poison         → poison-basic-vial
        cset = set(canon.split("-"))
        subset_matches = [
            o for o, ows in oracle_word_sets.items() if cset.issubset(ows) and len(ows - cset) <= 3
        ]
        if len(subset_matches) == 1:
            aliases[canon] = subset_matches[0]

    OUT.write_text(
        json.dumps(
            {
                "_comment": (
                    "canonical-slug → oracle-slug aliases. Derived by "
                    "tools/audit/derive_slug_aliases.py; hand-edited entries "
                    "permitted."
                ),
                "aliases": dict(sorted(aliases.items())),
            },
            indent=2,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    print(f"[slug-aliases] {len(aliases)} aliases written to {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
