# Comparison: what Nat20 is and isn't

Nat20 occupies a specific niche — a **deterministic, embeddable D&D 5e SRD
rules engine**. Knowing what it deliberately does *not* do is the fastest way
to decide whether it fits.

## What Nat20 is

- A **pure-Python, zero-I/O rules engine** for D&D 5e SRD 5.2 (CC-BY-4.0).
- **Deterministic and seedable** — same seed and inputs, same result. A
  rules oracle for tests, replays, bots, and AI hosts.
- A **typed content dataset** (`dnd5e-srd-data`) with a Foundry-aligned
  schema, loaded explicitly through `BundledAssetLoader`.
- **Host-agnostic** — it returns typed events and outcomes; how you render,
  narrate, store, or transport them is up to you.

## What Nat20 isn't

- **Not a VTT.** There's no map renderer, tokens, or UI. The grid is a
  movement/range model (`GridScene`), not a battle-map app.
- **Not a character-sheet app or builder UI.** `build_party_member` resolves
  a `CharacterBuildSpec` into combat stats; there's no interactive sheet.
- **Not a narration engine.** Nat20 decides *what happens* mechanically and
  deterministically; it does not write prose. Pair it with your own LLM or
  templating layer for narrative (that's exactly how Tapestria uses it).
- **Not a persistence layer.** Effects are combat-scoped; the engine holds no
  database. Cross-combat and long-term state are the host's job.

## Versus alternatives

| Need | Reach for |
|------|-----------|
| Tactical map + tokens + player UI | A VTT (Foundry, Roll20) |
| Discord dice + character commands | A bot framework (e.g. Avrae-style) |
| Deterministic 5e combat/check resolution as a library | **Nat20** |
| Hand-rolled `if`-ladders per spell/weapon | **Nat20** (typed activities) |

If you want a rules engine you can call from Python and trust to be
reproducible — without inheriting a VTT, a UI, or a narration model —
that's the gap Nat20 fills.
