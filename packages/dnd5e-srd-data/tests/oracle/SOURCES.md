# SRD Oracle Sources

Per-field source of truth for the assertion oracle in
`tests/test_canonical_against_oracle.py`.

All categories read from `raw_sources/five_e_bits/src/2024/en/` EXCEPT
spells (no 2024 file; see Decision D1 below).

## Monsters: `2024/en/5e-SRD-Monsters.json`
- `hp`, `ac` (first armor_class entry), ability scores, `cr`,
  `proficiency_bonus`, `saving_throws` (from proficiencies),
  `skills` (from proficiencies), `passive_perception` (from senses),
  `languages` (comma-split), damage lists, condition immunities.

## Items: `2024/en/5e-SRD-Equipment.json` + `2024/en/5e-SRD-Magic-Items.json`
- Equipment: weapon damage + versatile dice, properties, range,
  cost (denom-corrected), weight, armor base AC + dex bonus.
- Magic items: rarity + `requires_attunement` (parsed from desc).

## Spells: `2014/en/5e-SRD-Spells.json` (D1: no 2024 file)
- `level`, `school` (Foundry 3-letter code), `components` (V/S/M),
  `ritual`, `concentration`, `casting_time` (parsed → (n, unit)),
  `range` (parsed → Foundry-shaped dict), `duration` (parsed),
  `material`. The `classes` field is NOT emitted: 2024 SRD packs ship
  no spell→class tags, so it is uncheckable against 2024 canonical;
  class spell-lists are curated separately in PR 4b. Spell `damage`/`dc`
  live in Foundry's `activities` tree (separate activity oracle).

## Species: `2024/en/5e-SRD-Species.json`
- Foundry's per-lineage leaf slugs (elf-high/elf-wood/elf-drow,
  gnome-rock/gnome-forest, the three tiefling legacies) share one
  2024 5e-bits base entry; the rest map 1:1.
- `name`, `size`, `speed`, `traits` (provenance-only). The 2024 SRD
  dropped species ability-score bonuses and language grants (both moved
  to background), so neither is oracled.

## Backgrounds: `2024/en/5e-SRD-Backgrounds.json`
- `ability_options` (the three improvable abilities), `feat` (index),
  `skill_proficiencies` + `tool_proficiencies` (split from the
  `proficiencies` array's `skill-`/`tool-` indexes). 5e-bits ships
  only the four 2024 SRD backgrounds; the oracle check asserts only on
  slugs present in both canonical and the oracle.

## Feats: `2024/en/5e-SRD-Feats.json`
- `name`, `category` (derived from 5e-bits `type`: origin / general /
  fighting-style → fighting_style / epic-boon → epic_boon). 5e-bits
  ships all 17 2024 SRD feats keyed by `index` (matches canonical).

## Classes: `2024/en/5e-SRD-Classes.json`
- `hit_die`, `saving_throws`, `subclass_slugs`.

## Subclasses: `2024/en/5e-SRD-Subclasses.json`
- `class_slug` parent reference.

Slug is `index` (kebab-case) in both files — matches our canonical slug.
