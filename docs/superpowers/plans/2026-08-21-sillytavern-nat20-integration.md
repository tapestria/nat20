# SillyTavern ↔ nat20 Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `packages/nat20-bridge` (localhost FastAPI sidecar exposing the full nat20 engine, incl. homebrew overlay) and a `SillyTavern-nat20` UI extension (slash commands) so ST users resolve real 5e mechanics in chat.

**Architecture:** The extension (plain browser JS, no build step) talks HTTP to the bridge. The bridge is a host over the public `dnd5e_engine` API: it derives character sheets from `CharacterBuildSpec`, rolls initiative, threads seeded RNG, and renders `CombatEvent`s to narration text. Homebrew entries are schema-validated and served through an overlay `AssetLoader` injected via a new public `configure_lib_loader` engine seam.

**Tech Stack:** Python 3.12, FastAPI + uvicorn, pydantic v2, pytest (+ `fastapi.testclient`, needs `httpx`), uv workspace; extension: vanilla JS against SillyTavern's `SlashCommandParser` / `SillyTavern.getContext()`.

**Spec:** `docs/superpowers/specs/2026-08-21-sillytavern-plugin-design.md`

## Global Constraints

- Python `>=3.12`; ruff line-length 100, same lint select list as `packages/dnd5e-srd-data/pyproject.toml`; mypy on `src`; bandit `-r src/ -c pyproject.toml`.
- Bridge package version `0.3.0` (lockstep with engine/data); deps `dnd5e-engine>=0.3.0`, `dnd5e-srd-data>=0.3.0`.
- Coverage floor for the bridge: `--cov-fail-under=85` (baseline-and-ratchet: raise, never lower).
- Determinism: every dice roll in the bridge flows through a `random.Random(seed)`; never global `random`.
- Purity: no engine changes beyond Task 1; the engine stays host-agnostic.
- Homebrew slugs MUST be prefixed `hb-`; canonical entries are never shadowed (overlay checks base first — see Task 3).
- All bridge endpoints live under `/v1`. Bridge binds `127.0.0.1` by default.
- Licensing: engine/bridge code MIT; never embed non-SRD rules text. Extension repo license AGPLv3 (ST listing recommendation).
- Commit after every task; run the affected package's `make check` before claiming a task done.
- BACKLOG.md protocol: Task 1 adds+closes its engine-gap entry in the same commit.

## File Structure (bridge)

```
packages/nat20-bridge/
├── pyproject.toml
├── Makefile
├── README.md
├── src/nat20_bridge/
│   ├── __init__.py        # __version__
│   ├── app.py             # FastAPI app factory + routes (thin; delegates)
│   ├── cli.py             # console script: argparse + uvicorn.run
│   ├── overlay.py         # OverlayAssetLoader (homebrew-over-bundled)
│   ├── homebrew.py        # HomebrewStore: validate/persist/parse raw JSON
│   ├── forge.py           # forge_item(): compact recipe → schema-valid Weapon
│   ├── sheet.py           # derive_sheet(): CharacterBuildSpec+state → PartyMemberSpec
│   ├── slots.py           # SRD spell-slot tables by progression
│   ├── narrate.py         # CombatEvent → plain-text lines
│   └── state.py           # BridgeState: live combats dict, loader, homebrew path
└── tests/
    ├── conftest.py        # app fixture with tmp_path homebrew file
    ├── test_health.py
    ├── test_overlay.py
    ├── test_homebrew.py
    ├── test_forge.py
    ├── test_sheet.py
    ├── test_slots.py
    ├── test_narrate.py
    ├── test_roll_check.py
    ├── test_rest.py
    ├── test_combat_e2e.py
    └── test_srd_browse.py
```

Extension repo `~/Repos/SillyTavern-nat20/`: `manifest.json`, `index.js`, `settings.html`, `style.css`, `README.md`, `LICENSE`.

---

### Task 1: Engine seam — public `configure_lib_loader`

**Files:**
- Modify: `packages/dnd5e-engine/src/dnd5e_engine/lib_loader.py`
- Modify: `packages/dnd5e-engine/src/dnd5e_engine/__init__.py`
- Modify: `packages/dnd5e-engine/tests/test_public_api_surface.py` (add name to expected surface)
- Test: `packages/dnd5e-engine/tests/test_lib_loader_configure.py`
- Modify: `BACKLOG.md` (add + close `[loader-injection-host-seam]` in same commit; note in commit message)

**Interfaces:**
- Produces: `dnd5e_engine.configure_lib_loader(loader: AssetLoader | None) -> None` — installs a custom loader for all subsequent resolution; `None` reverts to lazy `BundledAssetLoader`.

- [ ] **Step 1: Write the failing tests**

```python
# packages/dnd5e-engine/tests/test_lib_loader_configure.py
"""configure_lib_loader — public host seam for AssetLoader injection."""

from dnd5e_srd_data.loader import BundledAssetLoader, MemoryAssetLoader

import dnd5e_engine
from dnd5e_engine.lib_loader import get_lib_loader


def test_configure_lib_loader_is_public() -> None:
    assert "configure_lib_loader" in dnd5e_engine.__all__


def test_configure_installs_and_none_reverts() -> None:
    custom = MemoryAssetLoader()
    try:
        dnd5e_engine.configure_lib_loader(custom)
        assert get_lib_loader() is custom
    finally:
        dnd5e_engine.configure_lib_loader(None)
    assert isinstance(get_lib_loader(), BundledAssetLoader)
```

- [ ] **Step 2: Run to verify failure**

Run: `cd packages/dnd5e-engine && uv run pytest tests/test_lib_loader_configure.py -q`
Expected: FAIL (`AttributeError: configure_lib_loader`)

- [ ] **Step 3: Implement**

In `lib_loader.py`, add below `set_lib_loader_for_tests` (keep that alias for existing tests) and extend `__all__`:

```python
def configure_lib_loader(loader: AssetLoader | None) -> None:
    """Public host seam: install a custom AssetLoader (e.g. a homebrew
    overlay). ``None`` reverts to the lazy bundled default. Hosts must
    call this before start_combat; swapping mid-combat is unsupported."""
    global _LIB_LOADER
    _LIB_LOADER = loader
```

In `__init__.py`: `from dnd5e_engine.lib_loader import configure_lib_loader` and add `"configure_lib_loader"` to `__all__` (alphabetical position). Update `tests/test_public_api_surface.py`'s expected-name list the same way.

- [ ] **Step 4: Run engine gate**

Run: `cd packages/dnd5e-engine && uv run pytest tests/test_lib_loader_configure.py tests/test_public_api_surface.py -q` then `make check`
Expected: PASS

- [ ] **Step 5: BACKLOG + commit**

Add to `BACKLOG.md` then delete in the same edit is pointless — instead note closure in the commit body.

```bash
git add -A && git commit -m "feat(engine): configure_lib_loader public host seam for AssetLoader injection"
```

---

### Task 2: Bridge package scaffold + `/v1/health` + workspace wiring

**Files:**
- Create: `packages/nat20-bridge/pyproject.toml`, `Makefile`, `README.md`, `src/nat20_bridge/__init__.py`, `src/nat20_bridge/app.py`, `src/nat20_bridge/state.py`, `src/nat20_bridge/cli.py`
- Create: `packages/nat20-bridge/tests/conftest.py`, `tests/test_health.py`
- Modify: root `Makefile` (add `check-bridge` to `check`), `.github/workflows/ci.yml` (mirror the srd-data job for nat20-bridge)

**Interfaces:**
- Produces: `create_app(state: BridgeState) -> FastAPI`; `BridgeState(homebrew_path: Path)` holding `combats: dict[str, CombatHandle]`, `events_log: dict[str, list[CombatEvent]]`, `seeds: dict[str, int]`; fixture `client` (TestClient) in conftest. All later tasks add routes inside `create_app` and tests via the `client` fixture.

- [ ] **Step 1: pyproject + Makefile**

`pyproject.toml`: copy `packages/dnd5e-srd-data/pyproject.toml` structure — name `nat20-bridge`, version `0.3.0`, `license = { text = "MIT" }`, dependencies `["dnd5e-engine>=0.3.0", "dnd5e-srd-data>=0.3.0", "fastapi>=0.115", "uvicorn>=0.30"]`, dev extra adds `httpx>=0.27` to the standard pytest/mypy/ruff/bandit set; `[project.scripts] nat20-bridge = "nat20_bridge.cli:main"`; same `[tool.ruff]` / `[tool.ruff.lint]` blocks; `[tool.uv.sources] dnd5e-engine = { workspace = true }` and same for `dnd5e-srd-data`; `[tool.bandit] exclude_dirs = ["tests"]`. `Makefile`: copy srd-data's `install`/`test`/`check` targets, `--cov=nat20_bridge --cov-fail-under=85`.

- [ ] **Step 2: Write failing health test**

```python
# tests/conftest.py
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nat20_bridge.app import create_app
from nat20_bridge.state import BridgeState


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(BridgeState(homebrew_path=tmp_path / "homebrew.json")))
```

```python
# tests/test_health.py
from fastapi.testclient import TestClient


def test_health_reports_versions(client: TestClient) -> None:
    resp = client.get("/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"bridge", "engine", "data"}
    assert body["bridge"] == "0.3.0"
```

- [ ] **Step 3: Run to verify failure** — `cd packages/nat20-bridge && uv sync --extra dev` (from root: `uv sync --all-packages --all-extras`), then `uv run pytest -q`. Expected: import error.

- [ ] **Step 4: Implement**

```python
# src/nat20_bridge/__init__.py
"""nat20-bridge — localhost HTTP host for the dnd5e-engine (SillyTavern sidecar)."""

__version__ = "0.3.0"
```

```python
# src/nat20_bridge/state.py
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dnd5e_engine import CombatEvent, CombatHandle


@dataclass
class BridgeState:
    homebrew_path: Path
    combats: dict[str, "CombatHandle"] = field(default_factory=dict)
    events_log: dict[str, list["CombatEvent"]] = field(default_factory=dict)
    seeds: dict[str, int] = field(default_factory=dict)
```

```python
# src/nat20_bridge/app.py
from __future__ import annotations

from importlib.metadata import version

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from nat20_bridge import __version__
from nat20_bridge.state import BridgeState


def create_app(state: BridgeState) -> FastAPI:
    app = FastAPI(title="nat20-bridge", version=__version__)
    # The ST extension fetches cross-origin from the SillyTavern page; the
    # bridge binds loopback so permissive CORS is acceptable here.
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
    )

    @app.get("/v1/health")
    def health() -> dict[str, str]:
        return {
            "bridge": __version__,
            "engine": version("dnd5e-engine"),
            "data": version("dnd5e-srd-data"),
        }

    return app
```

```python
# src/nat20_bridge/cli.py
from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from nat20_bridge.app import create_app
from nat20_bridge.state import BridgeState


def main() -> None:
    parser = argparse.ArgumentParser(prog="nat20-bridge")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8020)
    parser.add_argument(
        "--data-dir", type=Path, default=Path.home() / ".nat20-bridge",
        help="where homebrew.json persists",
    )
    args = parser.parse_args()
    args.data_dir.mkdir(parents=True, exist_ok=True)
    app = create_app(BridgeState(homebrew_path=args.data_dir / "homebrew.json"))
    uvicorn.run(app, host=args.host, port=args.port)
```

- [ ] **Step 5: Run + wire workspace** — `uv run pytest -q` → PASS. Root `Makefile`: add `check-bridge:` (`$(MAKE) -C packages/nat20-bridge check`) and append to `check:` deps. `.github/workflows/ci.yml`: duplicate the srd-data job pattern for nat20-bridge. Run `make check` in `packages/nat20-bridge`.

- [ ] **Step 6: Commit** — `git add -A && git commit -m "feat(bridge): nat20-bridge package scaffold with /v1/health"`

---

### Task 3: OverlayAssetLoader + HomebrewStore

**Files:**
- Create: `src/nat20_bridge/overlay.py`, `src/nat20_bridge/homebrew.py`
- Test: `tests/test_overlay.py`, `tests/test_homebrew.py`

**Interfaces:**
- Consumes: `dnd5e_srd_data.loader.AssetLoader`, `BundledAssetLoader`, `MemoryAssetLoader`, `Category`; schema models (`Item/Weapon/Armor/MagicItem/Monster/Spell/...`).
- Produces:
  - `HomebrewStore(path: Path)` with `.add(category: Category, raw: dict) -> str` (validates, enforces/normalizes `hb-` slug prefix, persists, returns slug; raises `HomebrewValidationError(str)` on schema failure or non-`hb-` collision), `.remove(slug: str) -> bool`, `.entries() -> dict[str, dict]` (slug → `{"category": ..., "raw": ...}`), `.as_memory_loader() -> MemoryAssetLoader`.
  - `OverlayAssetLoader(base: AssetLoader, overlay: MemoryAssetLoader)` implementing the full `AssetLoader` protocol: every `get_*` tries `base` first, then `overlay` (canonical never shadowed); `list_slugs` returns base + overlay; `__contains__` checks both.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_overlay.py
from dnd5e_srd_data.loader import BundledAssetLoader, MemoryAssetLoader
from dnd5e_srd_data.schema.item import Weapon

from nat20_bridge.overlay import OverlayAssetLoader


def _hb_weapon(slug: str = "hb-frost-brand") -> Weapon:
    base = BundledAssetLoader().get_weapon("longsword")
    assert base is not None
    return base.model_copy(update={"slug": slug, "name": "Frost Brand"})


def test_overlay_serves_homebrew_and_falls_through() -> None:
    loader = OverlayAssetLoader(
        base=BundledAssetLoader(),
        overlay=MemoryAssetLoader(items=[_hb_weapon()]),
    )
    assert loader.get_weapon("hb-frost-brand") is not None      # overlay hit
    assert loader.get_weapon("longsword") is not None            # base fallthrough
    assert loader.get_monster("goblin-warrior") is not None      # untouched category
    assert "hb-frost-brand" in loader.list_slugs("items")
    assert "longsword" in loader.list_slugs("items")
    assert ("items", "hb-frost-brand") in loader
    assert loader.get_weapon("hb-nope") is None


def test_canonical_is_never_shadowed() -> None:
    # An overlay entry that reuses a canonical slug must NOT win.
    rogue = MemoryAssetLoader(items=[_hb_weapon(slug="longsword")])
    loader = OverlayAssetLoader(base=BundledAssetLoader(), overlay=rogue)
    got = loader.get_weapon("longsword")
    assert got is not None and got.name != "Frost Brand"
```

```python
# tests/test_homebrew.py
import json
from pathlib import Path

import pytest
from dnd5e_srd_data.loader import BundledAssetLoader

from nat20_bridge.homebrew import HomebrewStore, HomebrewValidationError


def _raw_weapon(slug: str = "hb-frost-brand") -> dict:
    base = BundledAssetLoader().get_weapon("longsword")
    assert base is not None
    raw = json.loads(base.model_dump_json())
    raw["slug"], raw["name"] = slug, "Frost Brand"
    return raw


def test_add_validates_persists_and_reloads(tmp_path: Path) -> None:
    store = HomebrewStore(tmp_path / "homebrew.json")
    slug = store.add("items", _raw_weapon())
    assert slug == "hb-frost-brand"
    reloaded = HomebrewStore(tmp_path / "homebrew.json")
    assert reloaded.as_memory_loader().get_weapon("hb-frost-brand") is not None


def test_add_normalizes_missing_prefix(tmp_path: Path) -> None:
    store = HomebrewStore(tmp_path / "homebrew.json")
    assert store.add("items", _raw_weapon(slug="frost-brand")) == "hb-frost-brand"


def test_add_rejects_schema_garbage(tmp_path: Path) -> None:
    store = HomebrewStore(tmp_path / "homebrew.json")
    with pytest.raises(HomebrewValidationError):
        store.add("items", {"slug": "hb-junk", "item_kind": "weapon"})


def test_remove(tmp_path: Path) -> None:
    store = HomebrewStore(tmp_path / "homebrew.json")
    slug = store.add("items", _raw_weapon())
    assert store.remove(slug) is True
    assert store.remove(slug) is False
    assert store.as_memory_loader().get_weapon(slug) is None
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_overlay.py tests/test_homebrew.py -q` → import errors.

- [ ] **Step 3: Implement `overlay.py`** — a class with the 14 protocol methods; each `get_*` is `return self._base.get_x(slug) or self._overlay.get_x(slug)` EXCEPT use explicit `is None` checks (entries are models, but keep it explicit): `found = self._base.get_weapon(slug); return found if found is not None else self._overlay.get_weapon(slug)`. `list_slugs` = `base + [s for s in overlay if s not in base]`; `__contains__` delegates to both. Assert protocol conformance in module scope is unnecessary — the overlay test's `isinstance` is implicit via use; add `_: AssetLoader = OverlayAssetLoader(...)`-style check in test only if mypy needs it.

- [ ] **Step 4: Implement `homebrew.py`** — category → parse function map. Items dispatch on `raw.get("item_kind", "item")` exactly like `BundledAssetLoader.get_item` (weapon→`Weapon`, armor→`Armor`, magic_item→`MagicItem`, else `Item`); other categories map 1:1 (`monsters`→`Monster`, `spells`→`Spell`, `species`→`Species`, `classes`→`Class`, `subclasses`→`Subclass`, `backgrounds`→`Background`, `feats`→`Feat`, `features`→`Feature`). `add()`: normalize slug (`hb-` prefix if missing, also patch `raw["slug"]`), reject if the slug (sans prefix check) exists in `BundledAssetLoader` — actually simpler: prefix guarantees no canonical collision since no canonical slug starts with `hb-`; wrap `Model.model_validate(raw)` errors in `HomebrewValidationError(str(exc))`. Persist: JSON file `{slug: {"category": ..., "raw": ...}}`, written atomically (`path.with_suffix(".tmp")` then `os.replace`). Constructor loads the file if present, re-validating each entry (drop + warn on failures). `as_memory_loader()` groups parsed models by category into a `MemoryAssetLoader(items=[...], monsters=[...], ...)`.

- [ ] **Step 5: Run tests** — `uv run pytest tests/test_overlay.py tests/test_homebrew.py -q` → PASS; then `make check`.

- [ ] **Step 6: Commit** — `git commit -am "feat(bridge): homebrew store + overlay asset loader"`

---

### Task 4: Forge — compact recipe → schema-valid weapon

**Files:**
- Create: `src/nat20_bridge/forge.py`
- Test: `tests/test_forge.py`

**Interfaces:**
- Consumes: `BundledAssetLoader`, `Weapon`, `DamagePart` (`dnd5e_srd_data.schema.common`).
- Produces: `forge_item(*, name: str, base: str, loader: AssetLoader, bonus: int = 0, extra_damage: str | None = None) -> dict` — returns the RAW dict (json-roundtripped `Weapon`) ready for `HomebrewStore.add("items", raw)`. `extra_damage` format `"1d6:cold"`. Raises `ForgeError(str)` on unknown base slug / non-weapon base / malformed `extra_damage`. Slug derived from name: lowercase, spaces→`-`, `hb-` prefix.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_forge.py
import pytest
from dnd5e_srd_data.loader import BundledAssetLoader
from dnd5e_srd_data.schema.item import Weapon

from nat20_bridge.forge import ForgeError, forge_item


def test_forge_patches_name_slug_bonus_and_damage() -> None:
    raw = forge_item(
        name="Frost Brand", base="longsword", loader=BundledAssetLoader(),
        bonus=1, extra_damage="1d6:cold",
    )
    weapon = Weapon.model_validate(raw)
    assert weapon.slug == "hb-frost-brand"
    assert weapon.name == "Frost Brand"
    assert weapon.magical_bonus == 1
    assert any(p.dice == "1d6" and p.damage_type == "cold" for p in weapon.damage_parts)
    # base damage kept
    assert any(p.damage_type == "slashing" for p in weapon.damage_parts)


def test_forge_rejects_unknown_base_and_non_weapon() -> None:
    loader = BundledAssetLoader()
    with pytest.raises(ForgeError):
        forge_item(name="X", base="no-such-slug", loader=loader)
    with pytest.raises(ForgeError):
        forge_item(name="X", base="fireball", loader=loader)  # a spell, not an item


def test_forge_rejects_malformed_damage() -> None:
    with pytest.raises(ForgeError):
        forge_item(name="X", base="longsword", loader=BundledAssetLoader(),
                   extra_damage="coldish")
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_forge.py -q` → import error.

- [ ] **Step 3: Implement** — `loader.get_weapon(base)`; `None` → `ForgeError`. `extra_damage` regex `^(\d+d\d+(?:[+-]\d+)?):([a-z]+)$` → `DamagePart(dice=..., damage_type=...)`. Build via `weapon.model_copy(update={"slug": slug, "name": name, "magical_bonus": weapon.magical_bonus + bonus, "damage_parts": [*weapon.damage_parts, part]})`, then `json.loads(new.model_dump_json())` (round-trips `frozenset` properties etc. to raw JSON shape).

- [ ] **Step 4: Run** — PASS, then `make check`.
- [ ] **Step 5: Commit** — `git commit -am "feat(bridge): forge_item compact weapon recipes"`

---

### Task 5: Spell-slot tables (`slots.py`)

**Files:**
- Create: `src/nat20_bridge/slots.py`
- Test: `tests/test_slots.py`

**Interfaces:**
- Consumes: `Class.spellcasting.progression` values: `"full" | "half" | "third" | "pact" | "none"` (verify the Literal in `dnd5e_srd_data/schema/class_.py` at implementation time; treat unknown as `"none"`).
- Produces: `slots_for(progression: str, level: int) -> dict[int, int]` — `{slot_level: count}`, empty for `"none"`. SRD 5.2 single-class tables.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_slots.py
from nat20_bridge.slots import slots_for


def test_full_caster_landmarks() -> None:
    assert slots_for("full", 1) == {1: 2}
    assert slots_for("full", 3) == {1: 4, 2: 2}
    assert slots_for("full", 5) == {1: 4, 2: 3, 3: 2}
    assert slots_for("full", 20) == {1: 4, 2: 3, 3: 3, 4: 3, 5: 3, 6: 2, 7: 2, 8: 1, 9: 1}


def test_half_caster_landmarks() -> None:
    assert slots_for("half", 1) == {}
    assert slots_for("half", 2) == {1: 2}
    assert slots_for("half", 5) == {1: 4, 2: 2}


def test_pact_magic_landmarks() -> None:
    assert slots_for("pact", 1) == {1: 1}
    assert slots_for("pact", 5) == {3: 2}
    assert slots_for("pact", 17) == {5: 4}


def test_none_and_unknown() -> None:
    assert slots_for("none", 20) == {}
    assert slots_for("martial-nonsense", 20) == {}
```

- [ ] **Step 2: Verify failure**, then **Step 3: Implement** — three module-level tables copied from the SRD 5.2 class tables (Wizard table for full; Paladin table for half; Warlock Pact Magic for pact), each `list[dict[int, int]]` indexed `level-1`. IMPORTANT (memory: verify-rules-against-srd-text): transcribe the tables from `canonical/classes/wizard.json` / `paladin.json` / `warlock.json` `description` text (the class tables are embedded there) — do not trust model memory. `third` progression: `{}` for v1 (no SRD 5.2 base class uses it; leave a comment).

- [ ] **Step 4: Run + make check**, **Step 5: Commit** — `git commit -am "feat(bridge): SRD spell-slot progression tables"`

---

### Task 6: Sheet derivation (`sheet.py`) + `/v1/party/validate`

**Files:**
- Create: `src/nat20_bridge/sheet.py`
- Modify: `src/nat20_bridge/app.py` (route)
- Test: `tests/test_sheet.py`

**Interfaces:**
- Consumes: `dnd5e_engine.make_build_spec`, `build_party_member`, `CombatInstance`, `CharacterBuildSpec`; `slots_for` (Task 5); an `AssetLoader`.
- Produces:
  - `derive_sheet(spec: CharacterBuildSpec, *, name: str, entity_id: str, loader: AssetLoader, hp_current: int | None = None, spells_known: list[str] | None = None, zone_id: str = "0,0", initiative: int = 0) -> PartyMemberSpec`. Derivations:
    - ability mod: `(score - 10) // 2`
    - HP max: `die_max + con_mod + (level-1) * (die_max // 2 + 1 + con_mod)`, min 1/level; `die_max` from `loader.get_class(spec.class_slug).hit_die` (`"d6"` → 6)
    - AC: scan `spec.equipment` for armor entries (`loader.get_armor(slug)`): body armor → `base_ac + min(dex_mod, dex_bonus_max) if dex_bonus_max is not None else base_ac + dex_mod`, plus `magical_bonus`; shield category adds `2 + magical_bonus`; no body armor → `10 + dex_mod` (+ shield if any)
    - attack_bonus: proficiency (`2 + (level-1)//4`) + str_mod (v1 simplification; melee default)
    - spell_slots: `slots_for(cls.spellcasting.progression, level)`
    - spells_known: passed through (validated: every slug resolves via `loader.get_spell`, else `ValueError`)
    - hp_current defaults to hp_max
    - Delegates final assembly to `build_party_member(build_spec, CombatInstance(...), loader=loader)`, then `model_copy(update=...)` to fold in spell_slots/spells_known (CombatInstance carries them — pass directly).
  - Route `POST /v1/party/validate`: body `{"name", "entity_id"?, "build": {species_slug, class_slug, subclass_slug?, level, ability_scores: {str,dex,con,int,wis,cha}, equipment: [...]}, "spells_known": [...]?, "hp_current"?}` → 200 `{"member": <PartyMemberSpec dump>, "summary": "Elara — lvl 3 elf wizard, HP 17/17, AC 12, slots {1:4,2:2}"}` or 422 `{"detail": "<first error>"}`. `entity_id` defaults to `"char:" + slug-of-name`. Build the `CharacterBuildSpec` via `make_build_spec(...)` mapping `ability_scores` dict straight through.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_sheet.py
import pytest
from dnd5e_srd_data.loader import BundledAssetLoader
from fastapi.testclient import TestClient

from dnd5e_engine import make_build_spec
from nat20_bridge.sheet import derive_sheet

LOADER = BundledAssetLoader()


def _wizard(level: int = 3):
    return make_build_spec(
        species_slug="elf", class_slug="wizard", level=level,
        ability_scores={"str": 8, "dex": 14, "con": 13, "int": 15, "wis": 12, "cha": 10},
    )


def test_wizard_hp_ac_slots() -> None:
    m = derive_sheet(_wizard(), name="Elara", entity_id="char:elara", loader=LOADER,
                     spells_known=["fire-bolt", "magic-missile"])
    # d6 wizard, con 13 (+1): 6+1 + 2*(4+1) = 17
    assert m.hp_max == 17 and m.hp_current == 17
    assert m.ac == 12                       # unarmored 10 + dex(+2)
    assert m.spell_slots == {1: 4, 2: 2}    # full caster lvl 3
    assert m.spells_known == ["fire-bolt", "magic-missile"]
    assert m.character_level == 3 and m.class_slug == "wizard"


def test_fighter_armor_and_shield_ac() -> None:
    spec = make_build_spec(
        species_slug="human", class_slug="fighter", level=1,
        ability_scores={"str": 16, "dex": 14, "con": 14, "int": 10, "wis": 12, "cha": 8},
        equipment=("chain-mail", "shield"),
    )
    m = derive_sheet(spec, name="Brom", entity_id="char:brom", loader=LOADER)
    # chain mail 16 flat (dex cap 0) + shield 2
    assert m.ac == 18
    assert m.spell_slots == {}


def test_unknown_spell_slug_rejected() -> None:
    with pytest.raises(ValueError, match="wizzard-bolt"):
        derive_sheet(_wizard(), name="E", entity_id="char:e", loader=LOADER,
                     spells_known=["wizzard-bolt"])


def test_party_validate_route(client: TestClient) -> None:
    resp = client.post("/v1/party/validate", json={
        "name": "Elara",
        "build": {"species_slug": "elf", "class_slug": "wizard", "level": 3,
                  "ability_scores": {"str": 8, "dex": 14, "con": 13,
                                     "int": 15, "wis": 12, "cha": 10}},
        "spells_known": ["fire-bolt"],
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["member"]["hp_max"] == 17
    assert "Elara" in body["summary"]


def test_party_validate_route_bad_class(client: TestClient) -> None:
    resp = client.post("/v1/party/validate", json={
        "name": "X", "build": {"species_slug": "elf", "class_slug": "wizzard"}})
    assert resp.status_code == 422
    assert "wizzard" in resp.json()["detail"]
```

Pre-check at implementation time: confirm `chain-mail` / `shield` slugs exist (`ls canonical/items | grep -E 'chain|shield'`); adjust test slugs to the canonical ones if they differ (e.g. `chain-mail` vs `chainmail`). If chain mail's `dex_bonus_max` is `0` the formula gives 16; verify against the entry, not memory.

- [ ] **Step 2: Verify failure** → **Step 3: Implement** per the interface block. Keep route handlers thin: parse body → call `derive_sheet` → wrap `ValueError` into `HTTPException(422, str(exc))`.

- [ ] **Step 4: Run + make check**, **Step 5: Commit** — `git commit -am "feat(bridge): sheet derivation + /v1/party/validate"`

---

### Task 7: Narration renderer (`narrate.py`)

**Files:**
- Create: `src/nat20_bridge/narrate.py`
- Test: `tests/test_narrate.py`

**Interfaces:**
- Consumes: `dnd5e_engine.CombatEvent` union members (`dnd5e_engine.events`).
- Produces: `narrate(events: Sequence[CombatEvent], names: dict[str, str]) -> str` — one line per event, joined by `\n`; `names` maps entity_id → display name (fallback: the id). Unhandled event types render as `f"[{event.type}] " + compact key=value dump` — never raise.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_narrate.py
from dnd5e_engine.events import (
    AttackRolled, DamageApplied, Death, RoundStarted, TurnStarted,
)

from nat20_bridge.narrate import narrate

NAMES = {"char:elara": "Elara", "mon:gob-1": "Goblin 1"}


def test_attack_hit_line() -> None:
    text = narrate([
        AttackRolled(attacker_id="char:elara", target_id="mon:gob-1",
                     roll_total=18, advantage="none", is_crit=False, is_hit=True),
        DamageApplied(target_id="mon:gob-1", amount=6, damage_type="fire",
                      is_overkill=False),
    ], NAMES)
    lines = text.splitlines()
    assert "Elara" in lines[0] and "Goblin 1" in lines[0] and "18" in lines[0]
    assert "hit" in lines[0].lower()
    assert "6" in lines[1] and "fire" in lines[1]


def test_round_turn_death_lines() -> None:
    text = narrate([
        RoundStarted(round_number=2),
        TurnStarted(actor_id="mon:gob-1"),
        Death(entity_id="mon:gob-1"),
    ], NAMES)
    assert "Round 2" in text
    assert "Goblin 1" in text


def test_unknown_event_never_raises() -> None:
    from dnd5e_engine.events import DashTaken
    out = narrate([DashTaken.model_construct(type="dash_taken", actor_id="char:elara")],
                  NAMES)
    assert out  # some line rendered
```

NOTE: field names above (`advantage`, `entity_id` on `Death`, `DashTaken` fields) must be checked against `events.py` when writing the test — `AttackRolled`/`DamageApplied`/`RoundStarted`/`TurnStarted` are verified; confirm `Death`'s field (grep `class Death` in `events.py`) and construct minimal valid instances. Adjust the test to real fields, keep the assertions.

- [ ] **Step 2: Verify failure** → **Step 3: Implement** — a dict of `type` → format function for the ~10 high-traffic events (round/turn start-end, intent_submitted, attack_rolled incl. crit/miss wording, save_rolled, check_rolled, damage_applied, healing_applied, condition applied/removed, cast_failed, attack_failed, unconscious, death, combat_ended); generic fallback `f"[{e.type}] " + " ".join(f"{k}={v}" for k, v in e.model_dump().items() if k != "type")`. Helper `who = names.get(id, id)`.

- [ ] **Step 4: Run + make check**, **Step 5: Commit** — `git commit -am "feat(bridge): CombatEvent narration renderer"`

---

### Task 8: `/v1/roll`, `/v1/check`, `/v1/rest/*`

**Files:**
- Modify: `src/nat20_bridge/app.py`
- Test: `tests/test_roll_check.py`, `tests/test_rest.py`

**Interfaces:**
- Consumes: `dnd5e_engine.roll_dice_str`, `CheckSpec`, `resolve_check`, `HitDicePool`, `resolve_short_rest`, `resolve_long_rest`.
- Produces routes:
  - `POST /v1/roll` `{"dice": "2d6+3", "seed"?: int}` → `{"total": int, "dice": str}`. Check `roll_dice_str`'s signature at implementation (grep `def roll_dice_str` in `rules/effects.py`) — it takes an rng; thread `random.Random(seed)` (seed default: `secrets.randbits(32)`, echoed back as `"seed"`).
  - `POST /v1/check` `{"kind": "skill"|"ability"|"saving_throw", "ability": "dex", "skill"?: str, "dc"?: int, "ability_scores": {...}, "proficient_skills": [...], "proficient_saves": [...], "proficiency_bonus": int, "advantage"?: bool, "disadvantage"?: bool, "seed"?: int}` → full `CheckResult` dump + `"summary"` line. Inspect `CheckSpec`'s full field list (incl. rng/dc/advantage fields at `check.py:30-65`) when writing the route model.
  - `POST /v1/rest/short` `{"hit_die_size": 8, "dice_remaining": 3, "dice_total": 5, "dice_to_spend": 2, "con_modifier": 2, "hp_current": 10, "hp_max": 25, "seed"?: int}` → `{"healed": int, "dice_spent": int, "hp_current": int, "dice_remaining": int, "seed": int}` (clamp `hp_current + healed` to `hp_max`; 422 on engine `ValueError` overspend).
  - `POST /v1/rest/long` `{"hit_die_size", "dice_remaining", "dice_total", "hp_current", "hp_max"}` → same envelope shape.

- [ ] **Step 1: Write failing tests** — key assertions: same seed twice → identical totals (`/v1/roll` with `{"dice": "2d6+3", "seed": 42}` twice, equal); check route returns `success` bool when dc given and determinism by seed; short-rest overspend (`dice_to_spend > dice_remaining`) → 422; long rest → `hp_current == hp_max` and `dice_remaining == dice_total`.

```python
# tests/test_roll_check.py (core cases; extend with the ones above)
from fastapi.testclient import TestClient


def test_roll_deterministic_by_seed(client: TestClient) -> None:
    a = client.post("/v1/roll", json={"dice": "2d6+3", "seed": 42}).json()
    b = client.post("/v1/roll", json={"dice": "2d6+3", "seed": 42}).json()
    assert a["total"] == b["total"]
    assert 5 <= a["total"] <= 15


def test_check_route(client: TestClient) -> None:
    resp = client.post("/v1/check", json={
        "kind": "skill", "ability": "dex", "skill": "stealth", "dc": 10,
        "ability_scores": {"str": 10, "dex": 16, "con": 10, "int": 10, "wis": 10, "cha": 10},
        "proficient_skills": ["stealth"], "proficient_saves": [],
        "proficiency_bonus": 2, "seed": 7,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] in (True, False)
    assert "summary" in body
```

- [ ] **Step 2: Verify failure** → **Step 3: Implement** (route models as pydantic `BaseModel`s in `app.py` or a new `api_models.py` if `app.py` passes ~300 lines). → **Step 4: Run + make check** → **Step 5: Commit** — `git commit -am "feat(bridge): roll/check/rest endpoints"`

---

### Task 9: Combat lifecycle endpoints + seeded e2e

**Files:**
- Modify: `src/nat20_bridge/app.py`, `src/nat20_bridge/state.py`
- Test: `tests/test_combat_e2e.py`

**Interfaces:**
- Consumes: `start_combat`, `submit_player_intent`, `advance_monster_turn`, `end_combat`, `get_live`, `PlayerIntent`, `EncounterMemberSpec`, `GridScene`, `cell_id`, `configure_lib_loader` (Task 1), `OverlayAssetLoader`+`HomebrewStore` (Task 3), `derive_sheet` (Task 6), `narrate` (Task 7), `IntentRejectedError`/`UnknownHandleError` (`dnd5e_engine.orchestrator`).
- Produces routes (every combat response: `{"combat_id", "events": [<model_dump>...], "narration": str, "over": bool}`):
  - `POST /v1/combat` `{"party": [<same member shape as /v1/party/validate body>...], "monsters": ["goblin-warrior", "goblin-warrior"], "seed"?: int}`:
    1. `configure_lib_loader(OverlayAssetLoader(base=BundledAssetLoader(), overlay=store.as_memory_loader()))` (installed once at app startup and refreshed on homebrew mutation — see Task 10 note).
    2. rng = `random.Random(seed)`; initiative = `rng.randint(1,20) + dex_mod` per combatant.
    3. Party members via `derive_sheet` (grid start cells `cell_id(0, i)`); monsters: fetch `Monster` by slug (404 on unknown), instance ids `mon:{slug}-{n}`, `EncounterMemberSpec(entity_id=..., entity_type="Monster", name=f"{monster.name} {n}", initiative=..., hp_current=monster.hp, hp_max=monster.hp, ac=monster.ac or 10, dexterity=monster.ability_scores.dex, zone_id=cell_id(5, i), monster_template_slug=slug, creature_type=..., damage_resistances/immunities/vulnerabilities/condition_immunities=...)`.
    4. `await start_combat(session_id=combat_id, party=..., encounter=..., grid_scene=GridScene(width=12, height=12), rng_seed=seed)`; store handle + names map + events in `BridgeState`; `combat_id = f"c{len(state.combats)+1}"`.
  - `POST /v1/combat/{cid}/intent` `{"actor_id", "intent_type", "spell_id"?, "target_id"?, "item_id"?, "weapon_id"?, "feature_id"?, "target_zone_id"?}` → build `PlayerIntent` (pass only non-None fields), `await submit_player_intent`. New events = drain: capture via comparing `get_live` is wrong — instead register an event collector: `start_combat` returns opening events; subsequent events arrive on the handle's queue. Consume `narration_events(handle)` from a background task per combat that appends to `state.events_log[cid]`; each response returns events appended since the request began (track a per-request start index). Simpler deterministic alternative (PREFERRED, no task races): run the async engine calls with `asyncio.run`-style awaited FastAPI handlers and drain the queue non-blocking after each call — implement `_drain(handle) -> list[CombatEvent]` using `live.event_queue.get_nowait()` … but that's private. DECISION: use the collector-task approach but `await asyncio.sleep(0)` after each engine call and snapshot the log delta; the engine emits synchronously into the queue during the awaited call, so after it returns, pump the collector with `await asyncio.sleep(0)` in a loop until the log length stabilizes (bounded 100 iterations). Wrap `IntentRejectedError` → 409 `{"detail": reason}`, `UnknownHandleError`/unknown cid → 404.
  - `POST /v1/combat/{cid}/advance-monster` → `await advance_monster_turn(handle)`, same envelope; 409 on `IntentRejectedError` (PC's turn).
  - `GET /v1/combat/{cid}` → serialized `LiveCombatView`: `{"round_number", "current_actor": initiative[current_turn_index].entity_id-with-name, "order": [{"entity_id","name","hp","max_hp","dead","conditions","zone"}...], "ended"}` (hp from `tracked_hp`; names from stored map).
  - `POST /v1/combat/{cid}/end` → `await end_combat(handle)` → `{"outcome": <CombatOutcome dump>, "narration": ...}`; removes from registry.

- [ ] **Step 1: Write the failing e2e test**

```python
# tests/test_combat_e2e.py
from fastapi.testclient import TestClient

PARTY = [{
    "name": "Brom",
    "build": {"species_slug": "human", "class_slug": "fighter", "level": 3,
              "ability_scores": {"str": 16, "dex": 14, "con": 14,
                                 "int": 10, "wis": 12, "cha": 8},
              "equipment": ["chain-mail", "shield"]},
}]


def _start(client: TestClient, seed: int = 42) -> dict:
    resp = client.post("/v1/combat", json={
        "party": PARTY, "monsters": ["goblin-warrior"], "seed": seed})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_full_combat_flow(client: TestClient) -> None:
    start = _start(client)
    cid = start["combat_id"]
    assert start["narration"]           # initiative/turn-open narration present
    assert start["events"]

    view = client.get(f"/v1/combat/{cid}").json()
    ids = [row["entity_id"] for row in view["order"]]
    assert "char:brom" in ids and any(i.startswith("mon:goblin-warrior") for i in ids)

    # Drive up to 20 turns: attack on Brom's turn, advance on the goblin's.
    for _ in range(20):
        view = client.get(f"/v1/combat/{cid}").json()
        if view["ended"]:
            break
        if view["current_actor"].startswith("char:"):
            r = client.post(f"/v1/combat/{cid}/intent", json={
                "actor_id": "char:brom", "intent_type": "attack",
                "weapon_id": "longsword",
                "target_id": next(i for i in ids if i.startswith("mon:"))})
        else:
            r = client.post(f"/v1/combat/{cid}/advance-monster", json={})
        assert r.status_code == 200, r.text

    end = client.post(f"/v1/combat/{cid}/end", json={})
    assert end.status_code == 200
    assert end.json()["outcome"]["ended_reason"] in ("victory", "defeat_tpk", "forced")


def test_same_seed_same_narration(client: TestClient) -> None:
    a, b = _start(client, seed=7), _start(client, seed=7)
    assert a["narration"] == b["narration"]
    assert a["events"] == b["events"]


def test_wrong_turn_intent_is_409_unknown_combat_404(client: TestClient) -> None:
    start = _start(client, seed=1)
    cid = start["combat_id"]
    view = client.get(f"/v1/combat/{cid}").json()
    wrong = ("mon:goblin-warrior-1"
             if view["current_actor"].startswith("char:") else "char:brom")
    r = client.post(f"/v1/combat/{cid}/intent", json={
        "actor_id": wrong, "intent_type": "pass"})
    assert r.status_code == 409
    assert client.get("/v1/combat/nope").status_code == 404
```

CAVEAT for implementer: the attack may need Brom in range of the goblin on a grid — if `AttackFailed` events (out of range) stall the fight, either place party and monsters in adjacent cells (`cell_id(0,0)` / `cell_id(1,0)`) or submit `move` intents; adjust start-cell layout in the route (adjacent cells is the simple fix) — the test asserts flow, not victory.

- [ ] **Step 2: Verify failure** → **Step 3: Implement** per interface block (split routes into `src/nat20_bridge/routes_combat.py` with an `APIRouter` if `app.py` grows past ~300 lines; `create_app` includes it). → **Step 4: Run + make check** (note: `CombatOutcome.ended_reason` — verify field name in `outcome.py`, adjust test). → **Step 5: Commit** — `git commit -am "feat(bridge): combat lifecycle endpoints with seeded e2e"`

---

### Task 10: SRD browse + homebrew/forge endpoints

**Files:**
- Modify: `src/nat20_bridge/app.py` (or `routes_content.py`)
- Test: `tests/test_srd_browse.py`

**Interfaces:**
- Consumes: `HomebrewStore`, `forge_item`, the app's `OverlayAssetLoader`; `Category` literal values.
- Produces:
  - `GET /v1/srd/{category}?q=fire` → `{"slugs": [...]}` (all when no `q`; substring match on slug; 404 unknown category — validate against the 9 `Category` values).
  - `GET /v1/srd/{category}/{slug}` → raw entry dump (`model_dump(mode="json")`) or 404. Reads THROUGH the overlay so `hb-` entries resolve too.
  - `POST /v1/homebrew/{category}` body = raw entry JSON → `{"slug": "hb-..."} `; 422 with the `HomebrewValidationError` message.
  - `GET /v1/homebrew` → `{"entries": {slug: category}}`; `DELETE /v1/homebrew/{slug}` → 204 / 404.
  - `POST /v1/forge/item` `{"name", "base", "bonus"?: int, "extra_damage"?: "1d6:cold"}` → forge + auto-`store.add` → `{"slug", "summary": "Frost Brand (hb-frost-brand): longsword base, +1, +1d6 cold"}`; 422 on `ForgeError`.
  - After every homebrew mutation, rebuild + `configure_lib_loader(...)` with a fresh overlay (single helper `refresh_loader(state)` used by startup and mutations).

- [ ] **Step 1: Failing tests** — browse fireball (`GET /v1/srd/spells?q=fire` contains `"fireball"`; `GET /v1/srd/spells/fireball` 200 with `name == "Fireball"`); unknown category 404; forge→lookup roundtrip (`POST /v1/forge/item`, then `GET /v1/srd/items/hb-frost-brand` 200); homebrew import invalid → 422 mentioning the pydantic error; delete → 204 then lookup 404.
- [ ] **Step 2: Verify failure** → **Step 3: Implement** → **Step 4: Run + `make check`; also run root `make check`** (engine + data + bridge + examples all green). → **Step 5: Commit** — `git commit -am "feat(bridge): srd browse + homebrew/forge endpoints"`

---

### Task 11: Extension scaffold — manifest, settings panel, bridge client

**Files (new repo `~/Repos/SillyTavern-nat20/` — run `git init`, license AGPLv3):**
- Create: `manifest.json`, `index.js`, `settings.html`, `style.css`, `LICENSE`, `README.md`

**Interfaces:**
- Produces (consumed by Tasks 12-14, all in `index.js`): `bridgeFetch(path, {method, body}) -> Promise<object>` (throws `Error` with the server's `detail` on non-2xx); `getSettings()` returning `{bridgeUrl, roster}` persisted under `extensionSettings.nat20` (`roster`: `{[name]: {name, entity_id, build, spells_known, hp_current}}`); `postToChat(text)` — inserts a narrator message (see Step 3).

- [ ] **Step 1: manifest.json**

```json
{
    "display_name": "Nat20 Rules Engine",
    "loading_order": 100,
    "js": "index.js",
    "css": "style.css",
    "author": "tapestria",
    "version": "0.1.0",
    "homePage": "https://github.com/tapestria/SillyTavern-nat20",
    "auto_update": false
}
```

- [ ] **Step 2: settings.html + style.css** — a `.nat20-settings` inline-drawer block matching ST's settings idiom: text input `#nat20_bridge_url`, button `#nat20_test_connection`, status span `#nat20_status`, and a small "Homebrew JSON" textarea + import button (`#nat20_homebrew_json`, `#nat20_homebrew_import`). Keep styling minimal (ST inherits its theme).

- [ ] **Step 3: index.js core**

```javascript
const MODULE = 'nat20';
const DEFAULTS = { bridgeUrl: 'http://127.0.0.1:8020', roster: {} };

function getCtx() { return SillyTavern.getContext(); }

function getSettings() {
    const { extensionSettings } = getCtx();
    extensionSettings[MODULE] = { ...DEFAULTS, ...(extensionSettings[MODULE] ?? {}) };
    return extensionSettings[MODULE];
}

function saveSettings() { getCtx().saveSettingsDebounced(); }

async function bridgeFetch(path, { method = 'GET', body } = {}) {
    const url = getSettings().bridgeUrl.replace(/\/$/, '') + path;
    let resp;
    try {
        resp = await fetch(url, {
            method,
            headers: body ? { 'Content-Type': 'application/json' } : undefined,
            body: body ? JSON.stringify(body) : undefined,
        });
    } catch {
        throw new Error(`nat20-bridge unreachable at ${url} — is \`nat20-bridge\` running?`);
    }
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.detail ?? `bridge error ${resp.status}`);
    return data;
}

async function postToChat(text) {
    // Narrator-style message: lands in context so the LLM narrates around it.
    const ctx = getCtx();
    const message = {
        name: 'Nat20', is_user: false, is_system: false,
        send_date: Date.now(),
        mes: text, extra: { isSmallSys: false, api: 'nat20' },
    };
    ctx.chat.push(message);
    ctx.addOneMessage(message);
    await ctx.saveChat();
}
```

Settings wiring on init (`jQuery(async () => { ... })` per the st-extension-example template): load `settings.html` via `renderExtensionTemplateAsync('third-party/SillyTavern-nat20', 'settings')`, append to `#extensions_settings2`, bind url input ↔ settings, test-connection button → `bridgeFetch('/v1/health')` → paint `#nat20_status` green `bridge 0.3.0 · engine x.y.z` or red error text.

NOTE for implementer: `addOneMessage` / message-shape details drift across ST versions — mirror what `github.com/city-unit/st-extension-example` and a current bundled extension do (read from the user's ST install if present; otherwise fetch the example repo) rather than trusting the snippet blindly. Keep `postToChat` the single place that touches chat internals.

- [ ] **Step 4: README.md** — install steps (Extensions → Install extension → git URL; `uvx nat20-bridge` or `uv tool run nat20-bridge`; config.yaml NOT needed), command reference table (filled through Task 14), manual smoke script section (Task 14 Step 4).

- [ ] **Step 5: Commit (in the extension repo)** — `git add -A && git commit -m "feat: extension scaffold — settings panel + bridge client"`

---

### Task 12: Extension slash commands — dice, checks, saves, lookup

**Files:**
- Modify: `~/Repos/SillyTavern-nat20/index.js`

**Interfaces:**
- Consumes: `bridgeFetch`, `postToChat` (Task 11); ST's `SlashCommandParser`, `SlashCommand`, `SlashCommandNamedArgument`, `SlashCommandArgumentType` — obtained via `getCtx().SlashCommandParser` etc.; check availability the way the example extension imports them and prefer the context-provided handles.
- Produces slash commands: `/nat20-roll`, `/nat20-check`, `/nat20-save`, `/nat20-lookup`.

- [ ] **Step 1: Implement command registration**

```javascript
function registerCommands() {
    const { SlashCommandParser, SlashCommand, SlashCommandNamedArgument,
            ARGUMENT_TYPE } = getCtx();

    const cmd = (name, helpString, namedArgs, callback) =>
        SlashCommandParser.addCommandObject(SlashCommand.fromProps({
            name, helpString, namedArgumentList: namedArgs, callback,
        }));

    cmd('nat20-roll', 'Roll dice, e.g. /nat20-roll 2d6+3', [],
        async (_named, dice) => {
            const r = await run(() => bridgeFetch('/v1/roll',
                { method: 'POST', body: { dice: String(dice) } }));
            if (r) await postToChat(`🎲 ${dice} → **${r.total}**`);
            return r ? String(r.total) : '';
        });

    cmd('nat20-check',
        'Skill check for a roster PC: /nat20-check stealth pc=Elara dc=15',
        [
            SlashCommandNamedArgument.fromProps({ name: 'pc', typeList: ARGUMENT_TYPE.STRING }),
            SlashCommandNamedArgument.fromProps({ name: 'dc', typeList: ARGUMENT_TYPE.NUMBER }),
        ],
        async (named, skill) => checkCommand('skill', named, String(skill)));
    // /nat20-save mirrors nat20-check with kind='saving_throw' and the
    // unnamed arg = ability ('dex'); /nat20-lookup GETs /v1/srd/<category>
    // guessing category by trying spells, items, monsters in order and
    // posts name + summary of the first hit.
}

async function run(fn) {   // shared error funnel: bridge errors land in chat
    try { return await fn(); }
    catch (e) { await postToChat(`⚠️ nat20: ${e.message}`); return null; }
}
```

`checkCommand` builds the `/v1/check` body from the roster entry named by `pc=` (ability scores from `roster[pc].build.ability_scores`, proficiency bonus `2 + Math.floor((level-1)/4)`; `proficient_skills` — v1: empty list unless the roster entry carries a user-set `proficient_skills` array) and posts `📋 Elara Stealth check vs DC 15: **18** — success`.

- [ ] **Step 2: Manual verify** — with bridge running and extension symlinked into a local ST (`public/scripts/extensions/third-party/SillyTavern-nat20`), run `/nat20-roll 2d6+3` and `/nat20-check stealth pc=Elara dc=10` (after Task 13 adds Elara; for now assert the roster-missing error message appears). No automated JS tests (spec: extension stays thin; smoke via README script).

- [ ] **Step 3: Commit** — `git commit -am "feat: dice/check/save/lookup slash commands"`

---

### Task 13: Extension roster commands

**Files:**
- Modify: `~/Repos/SillyTavern-nat20/index.js`

**Interfaces:**
- Consumes: Task 11 helpers + `/v1/party/validate`, `/v1/rest/*`.
- Produces: `/nat20-pc`, `/nat20-pc-import`, `/nat20-party`, `/nat20-pc-remove`, `/nat20-equip`, `/nat20-rest`.

- [ ] **Step 1: Implement**
  - `/nat20-pc name=Elara class=wizard species=elf level=3 str=8 dex=14 con=13 int=15 wis=12 cha=10 spells=fire-bolt,magic-missile` — named args → `{"name", "build": {...}, "spells_known": [...]}` → `POST /v1/party/validate`; on 200 store `roster[name] = { ...requestBody, entity_id: r.member.entity_id, hp_current: r.member.hp_max }`, `saveSettings()`, `postToChat('✅ ' + r.summary)`; on error the `run()` funnel posts the 422 detail.
  - `/nat20-pc-import <json>` — `JSON.parse` the unnamed arg (parse errors → chat), same validate-and-store path.
  - `/nat20-party` — post a bullet list: name, class/level, HP `hp_current`, from re-validating each entry (`summary` field) or cached summaries.
  - `/nat20-pc-remove Elara`, `/nat20-equip Elara hb-frost-brand` (append slug to `build.equipment`, re-validate → new summary shows updated AC/attacks; on 422 roll back the append), `/nat20-rest short pc=Elara dice=2` / `/nat20-rest long pc=Elara` — map roster entry → `/v1/rest/*` body (hit die size from a small class→die map fetched via `GET /v1/srd/classes/<class_slug>` `hit_die` field; track `dice_remaining` on the roster entry, default `level`), write back returned `hp_current`/`dice_remaining`, post the healed line.

- [ ] **Step 2: Manual verify** — create Elara, `/nat20-party`, `/nat20-equip`, `/nat20-rest long pc=Elara`; restart ST and confirm roster survived (extensionSettings persistence).
- [ ] **Step 3: Commit** — `git commit -am "feat: roster management slash commands"`

---

### Task 14: Extension combat + content commands, README smoke

**Files:**
- Modify: `~/Repos/SillyTavern-nat20/index.js`, `README.md`

**Interfaces:**
- Consumes: Tasks 9-10 endpoints; roster (Task 13). Module-level `let activeCombatId = null`.
- Produces: `/nat20-fight`, `/nat20-attack`, `/nat20-cast`, `/nat20-use-item`, `/nat20-feature`, `/nat20-next`, `/nat20-status`, `/nat20-end`, `/nat20-homebrew-import`, `/nat20-forge-item`.

- [ ] **Step 1: Implement**
  - `/nat20-fight goblin-warrior goblin-warrior party=Elara,Brom` — unnamed args split on whitespace = monster slugs; `party=` names (default: whole roster; empty roster → chat error "No party — create one with /nat20-pc first"); body `{party: members, monsters, seed: Math.floor(Math.random()*2**31)}`; store `activeCombatId`; post the narration block.
  - Turn commands guard `activeCombatId` (error line if null). `/nat20-attack <target> weapon=<slug> pc=<name>` → intent body `{actor_id, intent_type:'attack', weapon_id, target_id}`; `actor_id` defaults to the current actor if it's a roster PC (fetch `GET /v1/combat/{id}` first). Target resolution: allow bare monster names — match against `order` entries by name prefix (case-insensitive) → entity_id. Same pattern for `/nat20-cast <spell-slug> <target>` (`intent_type:'cast_spell'`, `spell_id`), `/nat20-use-item`, `/nat20-feature`.
  - `/nat20-next` → advance-monster, post narration; `/nat20-status` → render the `GET` view as a markdown table (name, HP, conditions, ➤ marker on current actor); `/nat20-end` → post outcome summary (`ended_reason`, xp/loot if present), clear `activeCombatId`. Every combat response with `over: true` auto-posts "Combat over" and clears the id.
  - `/nat20-homebrew-import <json>` → `POST /v1/homebrew/items` unless the JSON has `entry_kind`/obvious category — v1 rule: named arg `category=` (default `items`). `/nat20-forge-item name="Frost Brand" base=longsword damage=1d6:cold bonus=1` → `/v1/forge/item` (`extra_damage` from `damage=`), post the returned summary.
- [ ] **Step 2: README** — full command reference + manual smoke script: start bridge → test connection → `/nat20-pc` (Elara) → `/nat20-forge-item` → `/nat20-equip` → `/nat20-fight goblin-warrior` → attack/next until over → `/nat20-end`. Each step lists the expected chat output shape.
- [ ] **Step 3: Manual verify** — run the README smoke script end-to-end against local ST + bridge. Fix what breaks before committing.
- [ ] **Step 4: Commit** — `git commit -am "feat: combat + homebrew slash commands; README smoke script"`

---

### Task 15: Docs + ship prep (nat20 repo)

**Files:**
- Modify: `README.md` (root — mention the bridge + link the extension repo), `docs/` (new page `docs/bridge.md` if docs nav fits; check `mkdocs.yml` nav), `BACKLOG.md` (close any bridge-related entries; add discovered gaps with date + file anchor, e.g. attack_bonus derivation ignoring dex/finesse in `packages/nat20-bridge/src/nat20_bridge/sheet.py`)

- [ ] **Step 1:** Write `docs/bridge.md`: what the bridge is, `uvx nat20-bridge`, endpoint table, homebrew format note, SillyTavern extension pointer. Add to `mkdocs.yml` nav. Run `uv run --group docs mkdocs build --strict`.
- [ ] **Step 2:** Root `make check` + `make smoke` green.
- [ ] **Step 3: Commit** — `git commit -am "docs: nat20-bridge + SillyTavern extension"`. Then use superpowers:finishing-a-development-branch (nat20 repo) — PR via the shipping-code flow needs the `tapestria` gh account (see HANDOFF note).

