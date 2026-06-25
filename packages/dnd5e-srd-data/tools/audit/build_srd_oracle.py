"""Build authoritative SRD oracle from 5e-bits/5e-database vendored snapshot.

Output:
- ``tests/oracle/srd_monster_oracle.json`` — keyed by SRD slug
- ``tests/oracle/srd_item_oracle.json`` — keyed by SRD slug (weapons + armor)
- ``tests/oracle/srd_spell_oracle.json`` — keyed by SRD slug
- ``tests/oracle/srd_species_oracle.json`` — keyed by Foundry species slug
  (per-lineage leaves share their 2024 5e-bits base entry)
- ``tests/oracle/srd_feat_oracle.json`` — keyed by SRD slug (2024 feats)
- ``tests/oracle/srd_class_oracle.json`` — keyed by SRD slug
- ``tests/oracle/srd_subclass_oracle.json`` — keyed by SRD slug
- ``tests/oracle/SOURCES.md`` — per-field provenance note

5e-bits ships clean JSON arrays per edition. All categories read from the 2024
snapshot (``raw_sources/five_e_bits/src/2024/en/``) EXCEPT spells: the 2024
snapshot has no ``5e-SRD-Spells.json``, so the spell oracle stays on the 2014
snapshot (``…/src/2014/en/``) — spell shape is edition-stable (Decision D1).

The oracle is the assertion target for ``tests/test_canonical_against_oracle.py``.
Anything in the oracle is what canonical MUST match (modulo
``tests/oracle/known_oracle_divergence.json`` exceptions).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
FIVE_E_BITS = ROOT / "raw_sources" / "five_e_bits" / "src" / "2014" / "en"
# The 2024 SRD edition. All EXISTING-category builders (monster, item, class,
# subclass) plus the new species/background/feat builders read from here. The
# ONLY builder still on 2014 is the spell oracle: the 2024 5e-bits snapshot
# ships no `5e-SRD-Spells.json` (Decision D1), and spell shape is edition-stable.
FIVE_E_BITS_2024 = ROOT / "raw_sources" / "five_e_bits" / "src" / "2024" / "en"
OUT_DIR = ROOT / "tests" / "oracle"

# 5e-bits damage_type/index uses snake-lowercase ("bludgeoning"). Foundry uses
# same. Keep both unchanged.

# Map 5e-bits "armor_category" → canonical lowercase enum value.
_ARMOR_CATEGORY = {"Light": "light", "Medium": "medium", "Heavy": "heavy", "Shield": "shield"}


# Map 5e-bits "weapon_category" + "weapon_range" → canonical 4-way category.
def _weapon_category(cat: str, rng: str) -> str:
    cat = (cat or "").lower()
    rng = (rng or "").lower()
    if cat == "simple" and rng == "melee":
        return "simple_melee"
    if cat == "simple" and rng == "ranged":
        return "simple_ranged"
    if cat == "martial" and rng == "melee":
        return "martial_melee"
    if cat == "martial" and rng == "ranged":
        return "martial_ranged"
    return "simple_melee"


# Map 5e-bits cost unit → gp multiplier.
_DENOM = {"cp": 0.01, "sp": 0.1, "ep": 0.5, "gp": 1.0, "pp": 10.0}


def _to_gp(cost: dict[str, Any] | None) -> float | None:
    if not cost:
        return None
    qty = cost.get("quantity")
    unit = (cost.get("unit") or "gp").lower()
    if qty is None:
        return None
    return float(qty) * _DENOM.get(unit, 1.0)


def _normalize_creature_type(raw: str) -> str:
    s = raw.lower().split(" (")[0].strip()
    # "swarm of Tiny beasts" → "beast" (the underlying creature type).
    m = re.match(r"swarm of\s+\w+\s+(\w+)s?$", s)
    if m:
        return m.group(1).rstrip("s")
    return s


def build_monster_oracle() -> dict[str, dict[str, Any]]:
    raw = json.loads((FIVE_E_BITS_2024 / "5e-SRD-Monsters.json").read_text())
    out: dict[str, dict[str, Any]] = {}
    for m in raw:
        slug = m["index"]
        # AC: 5e-bits ships a list of {type, value, ...}. The first entry is
        # the SRD's stated AC. We capture both the headline value and the
        # "type" so the test can decide whether we expect AC to be derived
        # from armor (which canonical leaves null).
        # AC: 5e-bits ships a list — some entries layer conditional AC
        # (e.g. dryad: 11 base, 16 with Barkskin). Capture both the FIRST
        # (base) and the maximum so the gate can accept either; Foundry
        # commonly bakes the buffed value into `attributes.ac.flat`.
        ac_list = m.get("armor_class") or []
        ac_values = [int(a["value"]) for a in ac_list if "value" in a]
        ac_value = ac_values[0] if ac_values else None
        ac_max = max(ac_values) if ac_values else None
        ac_type = ac_list[0].get("type") if ac_list else None
        # Saving throws: proficiencies with index "saving-throw-<ab>".
        saves: dict[str, int] = {}
        skills: dict[str, int] = {}
        for prof in m.get("proficiencies") or []:
            idx = prof.get("proficiency", {}).get("index") or ""
            if idx.startswith("saving-throw-"):
                saves[idx.removeprefix("saving-throw-")] = int(prof["value"])
            elif idx.startswith("skill-"):
                skill_name = idx.removeprefix("skill-").replace("-", "_")
                skills[skill_name] = int(prof["value"])
        senses = m.get("senses") or {}
        passive_perception = senses.get("passive_perception")
        # Languages: comma-separated string in 5e-bits.
        languages_raw = m.get("languages") or ""
        languages = (
            [s.strip() for s in languages_raw.split(",") if s.strip()] if languages_raw else []
        )
        out[slug] = {
            "name": m.get("name"),
            "creature_size": (m.get("size") or "").lower(),
            # 5e-bits ships strings like "humanoid (any race)" and
            # "swarm of Tiny beasts" — the latter resolves to the underlying
            # creature_type (beast). Strip parenthetical, then peel the
            # "swarm of <size> X" wrapper down to its core type.
            "creature_type": _normalize_creature_type(m.get("type") or ""),
            "alignment": m.get("alignment"),
            "hp": m.get("hit_points"),
            "hp_dice": m.get("hit_dice"),
            "ac": ac_value,
            "ac_max": ac_max,
            "ac_type": ac_type,  # advisory: "natural", "armor", "dex"…
            "ability_scores": {
                "str": m.get("strength"),
                "dex": m.get("dexterity"),
                "con": m.get("constitution"),
                "int": m.get("intelligence"),
                "wis": m.get("wisdom"),
                "cha": m.get("charisma"),
            },
            "cr": m.get("challenge_rating"),
            "proficiency_bonus": m.get("proficiency_bonus"),
            "saving_throws": saves,
            "skills": skills,
            "passive_perception": passive_perception,
            "languages": languages,
            "damage_resistances": m.get("damage_resistances") or [],
            "damage_immunities": m.get("damage_immunities") or [],
            "damage_vulnerabilities": m.get("damage_vulnerabilities") or [],
            "condition_immunities": [
                ci.get("name", "").lower() if isinstance(ci, dict) else str(ci).lower()
                for ci in (m.get("condition_immunities") or [])
            ],
        }
    return out


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(name: str) -> str:
    return _SLUG_RE.sub("-", name.lower()).strip("-")


def build_item_oracle() -> dict[str, dict[str, Any]]:
    """Build the item oracle from 5e-bits SRD equipment + magic items.

    Field-mapping notes:
    - ``5e-SRD-Equipment.json`` ships weapons, armor, AND mundane adventuring
      gear / tools / mounts / vehicles. We emit:
        * Weapons (`weapon_category` present) — full weapon entry with damage.
        * Armor (`armor_category` present) — armor entry with base AC + dex.
        * Everything else (mundane gear) — `kind="gear"` with `weight` +
          `cost_gp` only; no rarity in the source (SRD convention treats all
          non-magic gear as "common"), no attunement, no damage_parts.
    - Cost denomination map (cp=0.01, sp=0.1, ep=0.5, gp=1.0, pp=10.0) matches
      the translator's conversion.
    - Magic items (`5e-SRD-Magic-Items.json`) layer rarity + attunement on top
      of any existing entry (magic weapons live in Magic-Items, not Equipment).
    """
    raw = json.loads((FIVE_E_BITS_2024 / "5e-SRD-Equipment.json").read_text())
    magic = json.loads((FIVE_E_BITS_2024 / "5e-SRD-Magic-Items.json").read_text())
    out: dict[str, dict[str, Any]] = {}
    for e in raw:
        slug = e["index"]
        cost_gp = _to_gp(e.get("cost"))
        weight = e.get("weight")
        if e.get("weapon_category"):
            damage = e.get("damage") or {}
            two_handed_damage = e.get("two_handed_damage") or {}
            properties = [p["index"] for p in (e.get("properties") or [])]
            out[slug] = {
                "kind": "weapon",
                "name": e["name"],
                "weight": float(weight) if weight is not None else 0.0,
                "cost_gp": cost_gp,
                "weapon_category": _weapon_category(
                    e.get("weapon_category", ""), e.get("weapon_range", "")
                ),
                "damage_dice": damage.get("damage_dice"),
                "damage_type": (damage.get("damage_type") or {}).get("index"),
                "versatile_dice": (
                    two_handed_damage.get("damage_dice") if "versatile" in properties else None
                ),
                "properties": sorted(properties),
                "range_normal": (e.get("range") or {}).get("normal"),
                "range_long": (e.get("range") or {}).get("long"),
            }
        elif e.get("armor_category"):
            ac = e.get("armor_class") or {}
            out[slug] = {
                "kind": "armor",
                "name": e["name"],
                "weight": float(weight) if weight is not None else 0.0,
                "cost_gp": cost_gp,
                "armor_category": _ARMOR_CATEGORY.get(e.get("armor_category"), "light"),
                "base_ac": ac.get("base"),
                "dex_bonus": ac.get("dex_bonus"),
                "max_bonus": ac.get("max_bonus"),
                "stealth_disadvantage": e.get("stealth_disadvantage", False),
                "str_minimum": e.get("str_minimum") or None,
            }
        else:
            # Mundane adventuring gear / tools / mounts / vehicles. SRD ships
            # no rarity; the canonical translator emits "common" for non-magic
            # items. No attunement; no damage.
            out[slug] = {
                "kind": "gear",
                "name": e["name"],
                "weight": float(weight) if weight is not None else 0.0,
                "cost_gp": cost_gp,
                "rarity": "common",
                "requires_attunement": False,
                "equipment_category": (e.get("equipment_category") or {}).get("index"),
            }
    # Magic items: capture rarity + attunement requirement (NOT the prose).
    for m in magic:
        slug = m["index"]
        desc = " ".join(m.get("desc") or [])
        requires_attunement = "requires attunement" in desc.lower() or m.get("attunement") is True
        # Constraint phrase: parse "requires attunement <by ...>" from desc.
        constraint = None
        match = re.search(r"requires attunement\s+(by [^).]*)", desc, re.IGNORECASE)
        if match:
            constraint = match.group(1).strip().rstrip(".")
        out.setdefault(slug, {})
        # Magic items may overlap with equipment entries (e.g. magic weapons live
        # in Magic-Items, not Equipment). If we already saw it as a weapon/armor,
        # layer attunement on top; otherwise create a magic-item entry.
        existing = out[slug]
        existing.setdefault("kind", "magic")
        existing.setdefault("name", m["name"])
        existing["rarity"] = (m.get("rarity") or {}).get("name", "").lower().replace(
            " ", "_"
        ) or "common"
        existing["requires_attunement"] = bool(requires_attunement)
        existing["attunement_constraint"] = constraint
    return out


# --- Spells / races / classes / subclasses ---

# Foundry encodes the school as a 3-letter code ("evo", "abj", "div"...).
# 5e-bits ships full names ("Evocation"). The translator emits the Foundry
# code; the oracle canonicalises to the same 3-letter code so the test can
# compare directly.
_SCHOOL_CODE = {
    "abjuration": "abj",
    "conjuration": "con",
    "divination": "div",
    "enchantment": "enc",
    "evocation": "evo",
    "illusion": "ill",
    "necromancy": "nec",
    "transmutation": "trs",
}

# Foundry casting_time codes ("action", "bonus", "reaction", "minute", "hour")
# vs 5e-bits free-text ("1 action", "1 bonus action", "10 minutes"...).
# Compare on the normalised Foundry code + numeric value.
_CASTING_TIME_RE = re.compile(r"^(\d+)\s+(action|bonus action|reaction|minute|hour)s?\b", re.I)
_CASTING_TIME_UNIT = {
    "action": "action",
    "bonus action": "bonus",
    "reaction": "reaction",
    "minute": "minute",
    "hour": "hour",
}


def _parse_casting_time(s: str) -> tuple[int, str] | None:
    m = _CASTING_TIME_RE.match(s or "")
    if not m:
        return None
    return int(m.group(1)), _CASTING_TIME_UNIT[m.group(2).lower()]


# 5e-bits range: "Self", "Touch", "30 feet", "Sight", "Unlimited", "Special",
# "150 feet"... Foundry: dict{value: "150", units: "ft"} or
# dict{special: "Sight", units: "spec"}.
_RANGE_FEET_RE = re.compile(r"^(\d+)\s+feet$", re.I)
_RANGE_MILES_RE = re.compile(r"^(\d+)\s+miles?$", re.I)


def _parse_range(s: str) -> dict[str, Any]:
    s = (s or "").strip()
    if not s:
        return {"units": ""}
    low = s.lower()
    if low == "self":
        return {"units": "self"}
    if low == "touch":
        return {"units": "touch"}
    m = _RANGE_FEET_RE.match(s)
    if m:
        return {"units": "ft", "value": int(m.group(1))}
    m = _RANGE_MILES_RE.match(s)
    if m:
        return {"units": "mi", "value": int(m.group(1))}
    if low in {"sight", "unlimited", "special"}:
        return {"units": "any" if low == "unlimited" else "spec", "special": s}
    return {"units": "spec", "special": s}


# 5e-bits duration: "Instantaneous", "Concentration, up to 1 minute", "8 hours",
# "Until dispelled", "Up to 1 minute". Foundry: dict{value, units}.
_DURATION_RE = re.compile(r"(\d+)\s+(round|minute|hour|day)s?\b", re.I)


def _parse_duration(s: str) -> dict[str, Any]:
    s = (s or "").strip()
    if not s:
        return {"units": ""}
    low = s.lower()
    if low == "instantaneous":
        return {"units": "inst"}
    if low in {"until dispelled", "until dispelled or triggered"}:
        return {"units": "perm"}
    if low == "special":
        return {"units": "spec"}
    m = _DURATION_RE.search(s)
    if m:
        return {"units": m.group(2).lower(), "value": int(m.group(1))}
    return {"units": "spec", "raw": s}


def build_spell_oracle() -> dict[str, dict[str, Any]]:
    # D1: the 2024 5e-bits snapshot ships no `5e-SRD-Spells.json`, so this
    # builder stays on 2014. Spell shape (level/school/components/timing) is
    # edition-stable; 2024 only re-curates the per-class spell *lists*, which the
    # oracle no longer carries (the `classes` field is dropped in `_check_spell`).
    raw = json.loads((FIVE_E_BITS / "5e-SRD-Spells.json").read_text())
    out: dict[str, dict[str, Any]] = {}
    for s in raw:
        slug = s["index"]
        components = sorted({c.upper() for c in (s.get("components") or [])})
        school_name = ((s.get("school") or {}).get("name") or "").lower()
        out[slug] = {
            "name": s["name"],
            "level": s.get("level"),
            "school": _SCHOOL_CODE.get(school_name, school_name[:3]),
            "components": components,
            "ritual": bool(s.get("ritual", False)),
            "concentration": bool(s.get("concentration", False)),
            "casting_time": _parse_casting_time(s.get("casting_time") or ""),
            "range": _parse_range(s.get("range") or ""),
            "duration": _parse_duration(s.get("duration") or ""),
            "material": (s.get("material") or "").strip() or None,
            # No `classes`: 2024 SRD packs ship no spell→class tags, so this
            # field is uncheckable against 2024 canonical (D1). Class spell-lists
            # are curated separately in PR 4b.
        }
    return out


# Foundry creature_type/value for species is "humanoid" universally for the
# 2024 leaf species. 5e-bits ships a "type" on species ("Humanoid") — we don't
# oracle creature_type because the translator already preserves it verbatim.
# Size oracle uses 5e-bits "size" string ("Medium", "Small") downcased. The
# 2024 SRD removed species ability-score bonuses (ASIs derive from background),
# so the oracle no longer carries ``ability_bonuses``; species also no longer
# grant languages (that moved to background), so the oracle omits ``languages``.

# Map Foundry species slug → 5e-bits 2024 base index. The 2024 Foundry pack
# splits some species into per-lineage leaves (elf-high/elf-wood/elf-drow,
# gnome-rock/gnome-forest, the three tiefling legacies) that all share one
# 5e-bits base entry; the rest map 1:1.
_FOUNDRY_SPECIES_TO_BASE: dict[str, str] = {
    "dragonborn": "dragonborn",
    "dwarf": "dwarf",
    "elf-drow": "elf",
    "elf-high": "elf",
    "elf-wood": "elf",
    "gnome-forest": "gnome",
    "gnome-rock": "gnome",
    "goliath": "goliath",
    "halfling": "halfling",
    "human": "human",
    "orc": "orc",
    "tiefling-abyssal": "tiefling",
    "tiefling-chthonic": "tiefling",
    "tiefling-infernal": "tiefling",
}


def build_species_oracle() -> dict[str, dict[str, Any]]:
    species = {
        s["index"]: s for s in json.loads((FIVE_E_BITS_2024 / "5e-SRD-Species.json").read_text())
    }
    out: dict[str, dict[str, Any]] = {}
    for foundry_slug, base_slug in _FOUNDRY_SPECIES_TO_BASE.items():
        base = species.get(base_slug)
        if not base:
            continue
        out[foundry_slug] = {
            "name": base["name"],
            "size": (base.get("size") or "").lower(),
            "speed": base.get("speed"),
            # 5e-bits trait indices (e.g. "darkvision-60") are not directly
            # comparable to the Foundry feature UUIDs canonical carries, so
            # ``_check_species`` does not assert this field — kept for
            # provenance only.
            "traits": sorted(t["index"] for t in (base.get("traits") or [])),
        }
    return out


def build_background_oracle() -> dict[str, dict[str, Any]]:
    """Build the background oracle from the 2024 5e-bits SRD snapshot.

    5e-bits ships four 2024 SRD backgrounds (acolyte, criminal, sage, soldier).
    We capture the mechanical facts ``_check_background`` cross-checks:
    - ``ability_options``: the three improvable abilities (the +2/+1 pool).
    - ``feat``: the granted feat's index.
    - ``skill_proficiencies`` / ``tool_proficiencies``: split from the
      ``proficiencies`` array (5e-bits indexes them as ``skill-<name>`` /
      ``tool-<name>``), normalised to the bare proficiency name.
    """
    raw = json.loads((FIVE_E_BITS_2024 / "5e-SRD-Backgrounds.json").read_text())
    out: dict[str, dict[str, Any]] = {}
    for b in raw:
        slug = b["index"]
        ability_options = sorted(a["index"] for a in (b.get("ability_scores") or []))
        skills: list[str] = []
        tools: list[str] = []
        for prof in b.get("proficiencies") or []:
            idx = prof.get("index") or ""
            if idx.startswith("skill-"):
                skills.append(idx.removeprefix("skill-"))
            elif idx.startswith("tool-"):
                tools.append(idx.removeprefix("tool-"))
        out[slug] = {
            "name": b.get("name"),
            "ability_options": ability_options,
            "feat": (b.get("feat") or {}).get("index"),
            "skill_proficiencies": sorted(skills),
            "tool_proficiencies": sorted(tools),
        }
    return out


# 5e-bits feat ``type`` vocabulary → canonical FeatCategory value. The 5e-bits
# 2024 snapshot tags each feat with its category as a hyphenated string
# ("fighting-style", "epic-boon"); canonical uses snake-case. The four 5e-bits
# types map 1:1 onto the four FeatCategory members.
_FEAT_TYPE_TO_CATEGORY = {
    "origin": "origin",
    "general": "general",
    "fighting-style": "fighting_style",
    "epic-boon": "epic_boon",
}


def build_feat_oracle() -> dict[str, dict[str, Any]]:
    """Build the feat oracle from the 2024 5e-bits SRD snapshot.

    5e-bits ships the 17 2024 SRD feats keyed by an ``index`` slug that matches
    the Foundry/canonical slug 1:1. We capture ``name`` plus the ``category``
    derived from the 5e-bits ``type`` string — the two facts ``_check_feat``
    cross-checks. (Prerequisites and activity payloads diverge in vocabulary
    between the two sources and are pinned by the translator-fidelity test
    instead.)"""
    raw = json.loads((FIVE_E_BITS_2024 / "5e-SRD-Feats.json").read_text())
    out: dict[str, dict[str, Any]] = {}
    for f in raw:
        slug = f["index"]
        out[slug] = {
            "name": f.get("name"),
            "category": _FEAT_TYPE_TO_CATEGORY.get(f.get("type") or ""),
        }
    return out


def build_class_oracle() -> dict[str, dict[str, Any]]:
    raw = json.loads((FIVE_E_BITS_2024 / "5e-SRD-Classes.json").read_text())
    out: dict[str, dict[str, Any]] = {}
    for c in raw:
        slug = c["index"]
        out[slug] = {
            "name": c["name"],
            "hit_die": c.get("hit_die"),
            "saving_throws": sorted(st["index"] for st in (c.get("saving_throws") or [])),
            "subclass_slugs": sorted(s["index"] for s in (c.get("subclasses") or [])),
        }
    return out


def build_subclass_oracle() -> dict[str, dict[str, Any]]:
    raw = json.loads((FIVE_E_BITS_2024 / "5e-SRD-Subclasses.json").read_text())
    out: dict[str, dict[str, Any]] = {}
    for s in raw:
        slug = s["index"]
        out[slug] = {
            "name": s["name"],
            "class_slug": (s.get("class") or {}).get("index"),
        }
    return out


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    monsters = build_monster_oracle()
    items = build_item_oracle()
    spells = build_spell_oracle()
    species = build_species_oracle()
    backgrounds = build_background_oracle()
    feats = build_feat_oracle()
    classes = build_class_oracle()
    subclasses = build_subclass_oracle()
    (OUT_DIR / "srd_monster_oracle.json").write_text(
        json.dumps(monsters, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (OUT_DIR / "srd_item_oracle.json").write_text(
        json.dumps(items, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (OUT_DIR / "srd_spell_oracle.json").write_text(
        json.dumps(spells, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (OUT_DIR / "srd_species_oracle.json").write_text(
        json.dumps(species, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (OUT_DIR / "srd_background_oracle.json").write_text(
        json.dumps(backgrounds, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (OUT_DIR / "srd_feat_oracle.json").write_text(
        json.dumps(feats, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (OUT_DIR / "srd_class_oracle.json").write_text(
        json.dumps(classes, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (OUT_DIR / "srd_subclass_oracle.json").write_text(
        json.dumps(subclasses, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (OUT_DIR / "SOURCES.md").write_text(
        "# SRD Oracle Sources\n\n"
        "Per-field source of truth for the assertion oracle in\n"
        "`tests/test_canonical_against_oracle.py`.\n\n"
        "All categories read from `raw_sources/five_e_bits/src/2024/en/` EXCEPT\n"
        "spells (no 2024 file; see Decision D1 below).\n\n"
        "## Monsters: `2024/en/5e-SRD-Monsters.json`\n"
        "- `hp`, `ac` (first armor_class entry), ability scores, `cr`,\n"
        "  `proficiency_bonus`, `saving_throws` (from proficiencies),\n"
        "  `skills` (from proficiencies), `passive_perception` (from senses),\n"
        "  `languages` (comma-split), damage lists, condition immunities.\n\n"
        "## Items: `2024/en/5e-SRD-Equipment.json` + `2024/en/5e-SRD-Magic-Items.json`\n"
        "- Equipment: weapon damage + versatile dice, properties, range,\n"
        "  cost (denom-corrected), weight, armor base AC + dex bonus.\n"
        "- Magic items: rarity + `requires_attunement` (parsed from desc).\n\n"
        "## Spells: `2014/en/5e-SRD-Spells.json` (D1: no 2024 file)\n"
        "- `level`, `school` (Foundry 3-letter code), `components` (V/S/M),\n"
        "  `ritual`, `concentration`, `casting_time` (parsed → (n, unit)),\n"
        "  `range` (parsed → Foundry-shaped dict), `duration` (parsed),\n"
        "  `material`. The `classes` field is NOT emitted: 2024 SRD packs ship\n"
        "  no spell→class tags, so it is uncheckable against 2024 canonical;\n"
        "  class spell-lists are curated separately in PR 4b. Spell `damage`/`dc`\n"
        "  live in Foundry's `activities` tree (separate activity oracle).\n\n"
        "## Species: `2024/en/5e-SRD-Species.json`\n"
        "- Foundry's per-lineage leaf slugs (elf-high/elf-wood/elf-drow,\n"
        "  gnome-rock/gnome-forest, the three tiefling legacies) share one\n"
        "  2024 5e-bits base entry; the rest map 1:1.\n"
        "- `name`, `size`, `speed`, `traits` (provenance-only). The 2024 SRD\n"
        "  dropped species ability-score bonuses and language grants (both moved\n"
        "  to background), so neither is oracled.\n\n"
        "## Backgrounds: `2024/en/5e-SRD-Backgrounds.json`\n"
        "- `ability_options` (the three improvable abilities), `feat` (index),\n"
        "  `skill_proficiencies` + `tool_proficiencies` (split from the\n"
        "  `proficiencies` array's `skill-`/`tool-` indexes). 5e-bits ships\n"
        "  only the four 2024 SRD backgrounds; the oracle check asserts only on\n"
        "  slugs present in both canonical and the oracle.\n\n"
        "## Feats: `2024/en/5e-SRD-Feats.json`\n"
        "- `name`, `category` (derived from 5e-bits `type`: origin / general /\n"
        "  fighting-style → fighting_style / epic-boon → epic_boon). 5e-bits\n"
        "  ships all 17 2024 SRD feats keyed by `index` (matches canonical).\n\n"
        "## Classes: `2024/en/5e-SRD-Classes.json`\n"
        "- `hit_die`, `saving_throws`, `subclass_slugs`.\n\n"
        "## Subclasses: `2024/en/5e-SRD-Subclasses.json`\n"
        "- `class_slug` parent reference.\n\n"
        "Slug is `index` (kebab-case) in both files — matches our canonical slug.\n",
        encoding="utf-8",
    )
    print(
        f"[oracle] monsters={len(monsters)} items={len(items)} "
        f"spells={len(spells)} species={len(species)} "
        f"backgrounds={len(backgrounds)} feats={len(feats)} classes={len(classes)} "
        f"subclasses={len(subclasses)}"
    )
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
