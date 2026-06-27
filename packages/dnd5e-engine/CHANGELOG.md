# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.1]

### Added
- `LiveCombatView` — public read-model projection of live combat state.
- `get_live(handle) -> LiveCombatView` is now part of the public API (`__all__`);
  it returns a point-in-time snapshot view instead of the private `_LiveCombat`.
- `roll_dice_str` — the dice-expression evaluator is now a public test seam
  (renamed from the private `_roll_dice_str`).

## [0.1.0]

First public release.

### Added

- Pure-Python, host-agnostic D&D 5e SRD rules engine: combat orchestration,
  ability checks and saving throws, and combat-scoped effects.
- SRD 5.2 (2024) content resolution against the typed-Activity corpus via
  `BundledAssetLoader`, reading the canonical dataset from the
  `dnd5e-srd-data` package.
- Curated public API surface (`__all__`) with a surface guard test.
- `py.typed` marker — the package ships inline type information.
- Zero-I/O guarantee: no DB, network, or async dependencies in the engine.
