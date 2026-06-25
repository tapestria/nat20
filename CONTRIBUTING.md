# Contributing to Nat20

Thanks for your interest in improving Nat20, the pure-Python D&D 5e SRD 5.2
rules engine. This guide covers the workspace layout, dev setup, the CI gates
you must pass, and the licensing ground rules for contributions.

## Workspace layout

Nat20 is a single [`uv`](https://docs.astral.sh/uv/) workspace:

```
nat20/
├── packages/
│   ├── dnd5e-engine/     # the rules engine (MIT, code)
│   └── dnd5e-srd-data/   # the bundled SRD 5.2 dataset (CC-BY-4.0, data)
├── examples/             # verified-runnable usage examples
├── docs/                 # MkDocs sources
├── mkdocs.yml
└── pyproject.toml        # workspace root (not a published package)
```

`packages/*` are the workspace members. The engine ships no rules data; it
reads the dataset bundled by `dnd5e-srd-data` at runtime.

## Dev setup

From the repo root, sync every package and every extra into one environment:

```bash
uv sync --all-packages --all-extras
```

`--all-packages` installs all workspace members; `--all-extras` pulls in each
package's optional dependency groups (test, lint, type). The docs group is a
root dependency group — install it on demand with `--group docs` (see below).

## Running the gates

Each package has its own `make check`. Run it from the package directory before
opening a pull request.

### Engine (`packages/dnd5e-engine`)

```bash
cd packages/dnd5e-engine
make check                                   # ruff lint + mypy + pytest
bash scripts/smoke_clean_install.sh          # clean-install smoke: install + run a real grid combat
```

`make check` is hermetic — it needs no network and no raw upstream sources. The
smoke script verifies the package installs cleanly into a fresh environment and
that the public API actually runs.

### Dataset (`packages/dnd5e-srd-data`)

```bash
cd packages/dnd5e-srd-data
make check                                   # ruff lint + format check + mypy + pytest (hermetic)
```

The public `make check` here is **hermetic too**: it validates the shipped
`canonical/` corpus and does not require the raw upstream sources, which are not
distributed in this repo.

## Maintainer-only: regenerating the dataset

The `canonical/` corpus is the shipped product. Regenerating it from upstream is
a **maintainer flow** that needs the raw upstream sources (Foundry VTT dnd5e and
friends), which are **not** included in the public repo. If you have them
populated under `raw_sources/`:

```bash
cd packages/dnd5e-srd-data
make refresh-upstream     # pull/refresh the pinned raw upstream sources into raw_sources/
make check-provenance     # verify canonical/ still matches the pinned upstream pin + regen is clean
make regen                # re-run the translators to rebuild canonical/ from raw_sources/
```

`make check-provenance` runs the Foundry-pin audit and the regen-clean gate; it
requires `make refresh-upstream` to have populated `raw_sources/foundry` first.
A normal contributor will not run any of these — the hermetic `make check` is
the gate that matters for most changes.

## Documentation

Docs are MkDocs (Material). The `docs` dependency group lives at the workspace
root:

```bash
uv run --group docs mkdocs build --strict    # build (warnings are errors)
uv run --group docs mkdocs serve             # live-preview at http://127.0.0.1:8000
```

`--strict` is the gate: a broken link or missing reference fails the build.

## Trademark & licensing ground rules

Nat20 is split-licensed: **engine code is MIT, the SRD dataset is CC-BY-4.0**.
By contributing, you agree your contribution is offered under the license of the
package you are touching.

- **Code** (under `packages/dnd5e-engine`, examples, tooling): MIT.
- **Dataset** (under `packages/dnd5e-srd-data`): CC-BY-4.0, and it must preserve
  the upstream attribution chain (Foundry VTT dnd5e → open5e / 5e-bits → SRD 5.1
  and 5.2 by Wizards of the Coast LLC). Do not add rules content that is not
  traceable to a CC-BY-4.0 or compatibly-licensed source. Do **not** copy text
  from non-SRD D&D books or other proprietary sources.
- **Trademark safety**: Nat20 is an independent, unofficial project. It is
  **not affiliated with or endorsed by Wizards of the Coast**. In identity and
  positioning copy, prefer "5e" / "SRD" framing over "Dungeons & Dragons".
  "Dungeons & Dragons" and "D&D" are trademarks of Wizards of the Coast LLC;
  refer to them only nominatively, to identify the SRD ruleset this project
  implements. Do not imply official status, partnership, or endorsement.

See [`NOTICE`](NOTICE) for the consolidated provenance and attribution.
