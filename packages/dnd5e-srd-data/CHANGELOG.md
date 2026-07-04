# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
