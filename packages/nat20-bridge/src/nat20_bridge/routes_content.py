"""SRD browse + homebrew import/delete + item-forge routes.

Reads (`GET /v1/srd/...`) always go through ``state.loader`` — the
``OverlayAssetLoader`` installed by ``create_app`` — so homebrew (``hb-``)
entries resolve alongside canonical SRD content. Every homebrew mutation
(import, delete, forge-then-store) calls ``state.refresh_loader()`` so the
overlay (and the engine's module-global lib loader singleton) picks up the
change without a process restart.
"""

from __future__ import annotations

from typing import Any

from dnd5e_srd_data.loader import Category
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from nat20_bridge.forge import ForgeError, forge_item
from nat20_bridge.homebrew import HomebrewValidationError
from nat20_bridge.state import BridgeState

_CATEGORIES: tuple[Category, ...] = (
    "items",
    "monsters",
    "spells",
    "species",
    "classes",
    "subclasses",
    "backgrounds",
    "feats",
    "features",
)

# Category -> AssetLoader getter name, used to fetch a single entry for
# `GET /v1/srd/{category}/{slug}`.
_GETTERS: dict[str, str] = {
    "items": "get_item",
    "monsters": "get_monster",
    "spells": "get_spell",
    "species": "get_species",
    "classes": "get_class",
    "subclasses": "get_subclass",
    "backgrounds": "get_background",
    "feats": "get_feat",
    "features": "get_feature",
}


def _check_category(category: str) -> Category:
    if category not in _CATEGORIES:
        raise HTTPException(status_code=404, detail=f"unknown category: {category!r}")
    return category


class _ForgeItemRequest(BaseModel):
    name: str
    base: str
    bonus: int = 0
    extra_damage: str | None = None


def _forge_summary(name: str, slug: str, base: str, bonus: int, extra_damage: str | None) -> str:
    parts = [f"{base} base", f"+{bonus}"]
    if extra_damage is not None:
        dice, _, damage_type = extra_damage.partition(":")
        parts.append(f"+{dice} {damage_type}")
    return f"{name} ({slug}): {', '.join(parts)}"


def _browse(state: BridgeState, category: str, q: str | None) -> dict[str, Any]:
    checked = _check_category(category)
    assert state.loader is not None
    slugs = state.loader.list_slugs(checked)
    if q:
        slugs = [s for s in slugs if q in s]
    return {"slugs": slugs}


def _get_entry(state: BridgeState, category: str, slug: str) -> dict[str, Any]:
    checked = _check_category(category)
    assert state.loader is not None
    getter = getattr(state.loader, _GETTERS[checked])
    entry = getter(slug)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"unknown {checked} slug: {slug!r}")
    dumped: dict[str, Any] = entry.model_dump(mode="json")
    return dumped


def _homebrew_add(state: BridgeState, category: str, raw: dict[str, Any]) -> dict[str, str]:
    checked = _check_category(category)
    assert state.homebrew_store is not None
    assert state.refresh_loader is not None
    try:
        slug = state.homebrew_store.add(checked, raw)
    except HomebrewValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    state.refresh_loader()
    return {"slug": slug}


def _homebrew_list(state: BridgeState) -> dict[str, dict[str, str]]:
    assert state.homebrew_store is not None
    entries = state.homebrew_store.entries()
    return {"entries": {slug: entry["category"] for slug, entry in entries.items()}}


def _homebrew_delete(state: BridgeState, slug: str) -> None:
    assert state.homebrew_store is not None
    assert state.refresh_loader is not None
    removed = state.homebrew_store.remove(slug)
    if not removed:
        raise HTTPException(status_code=404, detail=f"unknown homebrew slug: {slug!r}")
    state.refresh_loader()


def _forge(state: BridgeState, req: _ForgeItemRequest) -> dict[str, str]:
    assert state.loader is not None
    assert state.homebrew_store is not None
    assert state.refresh_loader is not None
    try:
        raw = forge_item(
            name=req.name,
            base=req.base,
            loader=state.loader,
            bonus=req.bonus,
            extra_damage=req.extra_damage,
        )
    except ForgeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    slug = state.homebrew_store.add("items", raw)
    state.refresh_loader()
    summary = _forge_summary(req.name, slug, req.base, req.bonus, req.extra_damage)
    return {"slug": slug, "summary": summary}


def build_content_router(state: BridgeState) -> APIRouter:
    router = APIRouter()

    @router.get("/v1/srd/{category}")
    def browse(category: str, q: str | None = None) -> dict[str, Any]:
        return _browse(state, category, q)

    @router.get("/v1/srd/{category}/{slug}")
    def get_entry(category: str, slug: str) -> dict[str, Any]:
        return _get_entry(state, category, slug)

    @router.post("/v1/homebrew/{category}")
    def homebrew_add(category: str, raw: dict[str, Any]) -> dict[str, str]:
        return _homebrew_add(state, category, raw)

    @router.get("/v1/homebrew")
    def homebrew_list() -> dict[str, dict[str, str]]:
        return _homebrew_list(state)

    @router.delete("/v1/homebrew/{slug}", status_code=204)
    def homebrew_delete(slug: str) -> None:
        _homebrew_delete(state, slug)

    @router.post("/v1/forge/item")
    def forge(req: _ForgeItemRequest) -> dict[str, str]:
        return _forge(state, req)

    return router


__all__ = ["build_content_router"]
