"""Monster Armor Class from Foundry's ``calc: default`` (SRD 5.2).

133 Foundry actors ship ``attributes.ac.calc: default`` without a flat value:
Foundry computes their AC from the equipped armor and Dexterity when it
prepares the actor. The translator runs the same calculation, so every shipped
monster carries an Armor Class. These tests pin the derivation on raw actor
dicts and the canonical values the engine's Beast forms rely on (hermetic),
and, when raw sources are present, every derived AC against the SRD 5.2 stat
block's "Armor Class" line.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from dnd5e_srd_data import BundledAssetLoader
from tools.translators.foundry import _default_ac, _monster_ac, _with_actor_ac_calc

ROOT = Path(__file__).resolve().parent.parent
CANONICAL = ROOT / "src" / "dnd5e_srd_data" / "canonical" / "monsters"
PACKS = ROOT / "raw_sources" / "foundry" / "packs" / "_source"
SRD_MARKDOWN = (
    ROOT
    / "raw_sources"
    / "open5e"
    / "data"
    / "raw_sources"
    / "srd_5_2"
    / "starting-files"
    / "DND-SRD-5.2-CC.md"
)
DIVERGENCE = ROOT / "tests" / "oracle" / "known_oracle_divergence.json"
needs_raw = pytest.mark.skipif(
    not (PACKS.is_dir() and SRD_MARKDOWN.is_file()), reason="raw_sources not populated"
)

#: Monsters whose SRD 5.2 stat block has another name, with the sentence that
#: names it.
SRD_BLOCK_ALIASES = {
    # Phantom Steed: "The steed uses the Riding Horse stat block".
    "phantom-steed": "Riding Horse",
    # Figurine of Wondrous Power: "a Large goat with the same statistics as a Riding Horse".
    "goat-of-traveling": "Riding Horse",
}
#: Monsters with no SRD 5.2 stat block to compare against: Find Familiar names
#: the Octopus as a form, but the SRD prints only the Giant Octopus.
NO_SRD_BLOCK = frozenset({"octopus"})

DEX_16 = {"dex": {"value": 16}}


def _equipment(
    kind: str, value: int, dex: int | None = None, *, equipped: bool = True
) -> dict[str, Any]:
    return {
        "type": "equipment",
        "system": {
            "type": {"value": kind},
            "armor": {"value": value, "dex": dex},
            "equipped": equipped,
        },
    }


# ── The derivation (hermetic) ────────────────────────────────────────────────


def test_no_armor_is_ten_plus_the_dex_modifier() -> None:
    """SRD 5.2: "Without armor or a shield, your base Armor Class is 10 plus
    your Dexterity modifier." DEX 16 (+3) → 13."""
    assert _default_ac(DEX_16, []) == 13


def test_light_armor_adds_the_full_dex_modifier() -> None:
    """Leather Armor: "11 + Dex modifier" → 14."""
    assert _default_ac(DEX_16, [_equipment("light", 11)]) == 14


def test_medium_armor_caps_the_dex_modifier_at_two() -> None:
    """Breastplate: "14 + Dex modifier (max 2)" → 16, whether the item carries
    its cap or omits it."""
    assert _default_ac(DEX_16, [_equipment("medium", 14, 2)]) == 16
    assert _default_ac(DEX_16, [_equipment("medium", 14)]) == 16


def test_heavy_armor_ignores_dex() -> None:
    """Plate Armor: "18" → 18."""
    assert _default_ac(DEX_16, [_equipment("heavy", 18, 0)]) == 18


def test_a_shield_adds_its_value() -> None:
    """Shield: "+2" → Leather Armor 14 + 2 = 16; a Shield alone → 13 + 2."""
    assert _default_ac(DEX_16, [_equipment("light", 11), _equipment("shield", 2)]) == 16
    assert _default_ac(DEX_16, [_equipment("shield", 2)]) == 15


def test_only_the_first_equipped_armor_and_shield_count() -> None:
    """SRD 5.2: "A creature can wear only one suit of armor at a time and
    wield only one Shield at a time." Unequipped items never count."""
    items = [
        _equipment("heavy", 18, 0, equipped=False),
        _equipment("light", 11),
        _equipment("medium", 15, 2),
        _equipment("shield", 2),
        _equipment("shield", 2),
    ]
    assert _default_ac(DEX_16, items) == 16


def test_a_shipped_flat_value_wins_and_other_calculations_stay_unknown() -> None:
    """Only ``calc: default`` (and ``mage``) are derived: a flat value is kept
    verbatim, and a calculation the translator doesn't model stays ``None``
    rather than a guessed 10."""
    items = [_equipment("heavy", 18, 0)]
    assert _monster_ac({"calc": "natural", "flat": 17}, abilities=DEX_16, items=items) == 17
    assert _monster_ac({"calc": "default", "flat": None}, abilities=DEX_16, items=items) == 18
    assert _monster_ac({"calc": "custom", "flat": None}, abilities=DEX_16, items=items) is None


def test_an_actor_mage_armor_effect_sets_the_mage_calculation() -> None:
    """SRD 5.2 Mage Armor: "the target's base AC becomes 13 plus its
    Dexterity modifier". Foundry applies an actor's own enabled effects before
    it prepares AC, so the Mage's effect (``calc`` → ``mage``) gives 13 + 2."""
    mage_armor = {
        "disabled": False,
        "changes": [{"key": "system.attributes.ac.calc", "mode": 5, "value": "mage"}],
    }
    ac_doc = _with_actor_ac_calc({"calc": "default", "flat": None}, [mage_armor])
    assert _monster_ac(ac_doc, abilities={"dex": {"value": 14}}, items=[]) == 15
    disabled = {**mage_armor, "disabled": True}
    assert _with_actor_ac_calc({"calc": "default", "flat": None}, [disabled])["calc"] == "default"


# ── The canonical corpus (hermetic) ──────────────────────────────────────────


def test_every_shipped_monster_has_an_armor_class() -> None:
    missing = [
        path.stem
        for path in sorted(CANONICAL.glob("*.json"))
        if json.loads(path.read_text(encoding="utf-8"))["ac"] is None
    ]
    assert missing == []


@pytest.mark.parametrize(
    ("slug", "ac"),
    [
        ("rat", 10),
        ("riding-horse", 11),
        ("spider", 12),
        ("wolf", 12),
        ("black-bear", 11),
        ("brown-bear", 11),
        ("giant-bat", 13),
        ("ape", 12),
        ("giant-badger", 13),
        ("tough", 12),
        ("knight", 18),
        ("noble", 15),
        ("mage", 15),
    ],
)
def test_srd_armor_class_pins(slug: str, ac: int) -> None:
    """The SRD 5.2 "Armor Class" of the four SRD-recommended Wild Shape forms
    (Rat, Riding Horse, Spider, Wolf), the Beast forms the engine tests use,
    and one monster per derivation path: Tough (Leather Armor), Knight (Plate
    Armor), Noble (Breastplate), Mage (Mage Armor); Giant Badger ships a flat
    13 and is unchanged."""
    monster = BundledAssetLoader().get_monster(slug)
    assert monster is not None
    assert monster.ac == ac


# ── Every derived AC against the SRD 5.2 markdown (raw sources) ─────────────


def _srd_armor_classes() -> dict[str, int]:
    """Stat-block name → the first "- **Armor Class:** N" line under its
    "## " heading."""
    found: dict[str, int] = {}
    heading: str | None = None
    for line in SRD_MARKDOWN.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            heading = line[3:].strip()
        match = re.fullmatch(r"- \*\*Armor Class:\*\* (\d+)", line)
        if match and heading is not None and heading not in found:
            found[heading] = int(match.group(1))
    return found


def _derived(canonical: dict[str, Any]) -> bool:
    """True when the raw actor ships no flat value or formula, so its canonical
    AC comes from the derivation."""
    relative = canonical["provenance"]["source_url"].split("/packs/_source/", 1)[1]
    raw = yaml.safe_load((PACKS / relative).read_text(encoding="utf-8"))
    ac_doc = raw["system"]["attributes"].get("ac") or {}
    flat = ac_doc.get("flat")
    return not (isinstance(flat, int) and flat > 0) and not ac_doc.get("formula")


@needs_raw
def test_every_derived_ac_matches_the_srd_stat_block() -> None:
    srd = _srd_armor_classes()
    divergence = json.loads(DIVERGENCE.read_text(encoding="utf-8"))
    derived = [
        entry
        for path in sorted(CANONICAL.glob("*.json"))
        if _derived(entry := json.loads(path.read_text(encoding="utf-8")))
    ]
    assert len(derived) == 133
    mismatches: list[str] = []
    stale: list[str] = []
    for entry in derived:
        slug = entry["slug"]
        if slug in NO_SRD_BLOCK:
            continue
        expected = srd[SRD_BLOCK_ALIASES.get(slug, entry["name"])]
        known = "ac" in divergence.get(slug, {})
        if entry["ac"] != expected and not known:
            mismatches.append(f"{slug}: canonical {entry['ac']} vs SRD {expected}")
        if entry["ac"] == expected and known:
            stale.append(slug)
    assert mismatches == []
    assert stale == []
