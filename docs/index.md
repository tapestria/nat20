# Nat20 — a pure-Python D&D 5e SRD rules engine

**Nat20** is an open-source **Python D&D 5e engine**: a host-agnostic,
zero-I/O **5e SRD 5.2 rules engine** plus a typed content **dataset**. It
resolves combat, skill checks, saving throws, effects, and grid movement
deterministically — give it a seed and the same inputs always produce the
same outcome. No database, no network, no global state: a TTRPG combat
engine you can drop into a game server, a bot, a VTT backend, or a test
harness.

!!! warning "Legal / trademark notice"

    Nat20 implements the **D&D 5e System Reference Document (SRD 5.2)**,
    licensed **CC-BY-4.0**. It is **not affiliated with, endorsed by, or
    sponsored by Wizards of the Coast.** "Dungeons & Dragons" and "D&D" are
    trademarks of Wizards of the Coast LLC. Nat20 uses only SRD content and
    the generic "5e" descriptor.

## Why Nat20

- **Deterministic, seedable engine.** Every roll flows through a seeded RNG,
  so combat is reproducible — ideal for tests, replays, and AI-driven hosts
  that need a rules oracle.
- **Pure Python, zero I/O.** The engine performs no I/O of its own. Content
  loads through the companion `dnd5e-srd-data` package via an explicit
  `BundledAssetLoader`. Easy to embed, easy to reason about.
- **SRD 5.2 (2024).** Backgrounds, origin feats, weapon mastery, and the
  2024 ruleset — the edition new tooling is converging on.
- **Typed, Foundry-aligned data model.** Activities, effects, and specs use
  Pydantic models that mirror the Foundry VTT dnd5e schema rather than
  bespoke shapes.
- **Two packages, one workspace.** `dnd5e-engine` (the rules engine) and
  `dnd5e-srd-data` (the CC-BY-4.0 SRD 5.2 corpus).

## What you get

A small, explicit public API — `start_combat`, `submit_player_intent`,
`advance_monster_turn`, `end_combat` for the combat loop; `resolve_check`
for one-shot ability/skill/saving-throw rolls; `build_party_member` to turn
a `CharacterBuildSpec` into a combat-ready party member; and a `GridScene`
for 2-D battlefield movement.

[Get started in ~20 lines →](quickstart.md){ .md-button .md-button--primary }
[Browse the API →](api.md){ .md-button }

---

<sub>Nat20 is used in production by [Tapestria](https://tapestria.com), an
AI-driven MUD TTRPG, as its deterministic rules oracle.</sub>
