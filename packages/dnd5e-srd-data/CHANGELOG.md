# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

No schema or canonical-content changes. The `dnd5e-engine` core-mechanics
foundations (F1–F3) read the existing corpus unchanged — see
[`docs/migration/v0.5-to-v0.6.md`](../../docs/migration/v0.5-to-v0.6.md).

## [0.5.0]

Lockstep release with `dnd5e-engine` 0.5.0 and `nat20-bridge` 0.5.0.

No schema or canonical-content changes.

## [0.4.0]

Lockstep release with `dnd5e-engine` 0.4.0 and `nat20-bridge` 0.4.0.

No schema or canonical-content changes.

## [0.3.2]

Lockstep release with `dnd5e-engine` 0.3.2 and `nat20-bridge` 0.3.2.

No schema or canonical-content changes.

### Fixed

- `__version__` derives from installed package metadata (0.3.0 shipped reporting
  `0.2.0`).

### Added

- **Oracle coverage floors** (`tests/test_oracle_coverage_floor.py`). The
  fidelity suite compares canonical entries only against slugs the oracle
  contains, silently skipping the rest — so it reported green while the monster
  oracle covered **3 of 341 monsters**. Coverage is now a tested property with a
  per-category floor pinned at today's ratio, to be ratcheted upward.
- **Corpus prose integrity gate** (`tests/test_corpus_prose_integrity.py`).
  Fails on unsubstituted template placeholders in shipped descriptions. It found
  `monsters/ancient-gold-dragon` shipping `"makes {count} [[/item]] attacks"`;
  registered as an upstream defect in `tests/oracle/known_prose_defects.json`
  rather than hand-edited (the corpus is translator output).

### Changed

- Coverage floor raised 90 → 96 (actual 96.2%).

## [0.3.0]

Lockstep release with `dnd5e-engine` 0.3.0 (the release workflow publishes both
packages together). All schema changes below are additive — every new field is
nullable/defaulted, no existing field moved or changed value, and canonical
output stays byte-deterministic (`make check-regen-clean`). See
`docs/migration/v0.2-to-v0.3.md` for the full, host-facing migration guide.

### Added
- **Item charge pools** — `Item.uses: ItemUses | None` (Foundry `system.uses`: `max`,
  `spent`, `auto_destroy`, `recovery[]`). Regen populated 225 of 546 canonical items;
  the rest carry `"uses": null`. `RecoveryPeriod` gains `"dawn"` and `"dusk"`.
- **Spell uuid join key** — `Spell.foundry_uuid` (full `Compendium.dnd5e.<pack>.Item.<_id>`)
  on all 339 canonical spells, plus `AssetLoader.get_spell_by_uuid` (lazy index on
  `BundledAssetLoader`). Enables `CastActivity` uuid→Spell delegation in the engine.

### Changed
- `AssetLoader` protocol gained a required member (`get_spell_by_uuid`) — third-party
  implementers must add it. Both bundled implementations already carry it.

## [0.2.0]

Lockstep release with `dnd5e-engine` 0.2.0 (the release workflow publishes both
packages together). All schema changes below are additive — every new field is
nullable/defaulted, no existing field moved or changed value, and canonical
output stays byte-deterministic (`make check-regen-clean`).

### Added

- **`Feature.uses`** schema field (`FeatureUses`, `RecoveryRule` models) —
  carries a feature's Foundry top-level `system.uses` cap (Second Wind's capped,
  rest-recharged pool), threaded by the translator. Regenerating the canonical
  corpus added a nullable `"uses"` key to all 260 `canonical/features/*.json`
  files (47 populated, 213 `null`).
- **`Feature.advancement`** schema field — carries a feature's own
  `system.advancement[]` (ScaleValue tables owned by a granted feature, e.g.
  Channel Divinity). Regeneration added an `"advancement"` key to every
  `canonical/features/*.json` (non-empty only where the source YAML carries it).
- **`applied_effects`** field on the relevant activity schema — models Foundry's
  legacy flat `appliedEffects` id list for round-trip fidelity.

### Changed

- **SRD-correct spell damage types** — a translator override corrects damage
  types for spells whose upstream source left them typeless/mislabeled, so
  canonical spell JSON now reflects the SRD 5.2 text. Affected `canonical/spells/*.json`
  regenerated deterministically.
## [0.1.2]

Lockstep version bump; no content change.

## [0.1.1]

No content changes — version bump only, to release in lockstep with
`dnd5e-engine` 0.1.1 (the release workflow publishes both packages).

## [0.1.0]

First public release.

### Added

- Canonical D&D 5e SRD asset dataset (SRD 5.1 and 5.2), distributed under
  CC-BY-4.0 with full provenance attribution (see `NOTICE`).
- Canonical JSON shipped inside the package for `importlib.resources` lookup.
- `py.typed` marker — the package ships inline type information.
