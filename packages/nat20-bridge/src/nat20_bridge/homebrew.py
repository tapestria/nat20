"""HomebrewStore — validated, persisted homebrew content overlay.

Homebrew entries are stored as raw dicts on disk (keyed by slug), re-parsed
through the same Pydantic schema models the canonical dataset uses, and
exposed as a :class:`~dnd5e_srd_data.loader.MemoryAssetLoader` so they can be
layered under :class:`~nat20_bridge.overlay.OverlayAssetLoader`.

Every homebrew slug is forced to carry an ``hb-`` prefix. Since no canonical
SRD slug starts with ``hb-``, this guarantees homebrew content can never
collide with (and therefore never shadow) canonical content.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from dnd5e_srd_data.loader import Category, MemoryAssetLoader
from dnd5e_srd_data.schema.background import Background
from dnd5e_srd_data.schema.class_ import Class, Subclass
from dnd5e_srd_data.schema.feat import Feat
from dnd5e_srd_data.schema.feature import Feature
from dnd5e_srd_data.schema.item import Armor, Item, MagicItem, Weapon
from dnd5e_srd_data.schema.monster import Monster
from dnd5e_srd_data.schema.species import Species
from dnd5e_srd_data.schema.spell import Spell
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

_HB_PREFIX = "hb-"


class HomebrewValidationError(Exception):
    """Raised when a homebrew entry fails schema validation."""


def _parse_item(raw: dict[str, Any]) -> Item | Weapon | Armor | MagicItem:
    kind = raw.get("item_kind", "item")
    if kind == "weapon":
        return Weapon.model_validate(raw)
    if kind == "armor":
        return Armor.model_validate(raw)
    if kind == "magic_item":
        return MagicItem.model_validate(raw)
    return Item.model_validate(raw)


_PARSERS: dict[str, Any] = {
    "items": _parse_item,
    "monsters": Monster.model_validate,
    "spells": Spell.model_validate,
    "species": Species.model_validate,
    "classes": Class.model_validate,
    "subclasses": Subclass.model_validate,
    "backgrounds": Background.model_validate,
    "feats": Feat.model_validate,
    "features": Feature.model_validate,
}


def _normalize_slug(raw: dict[str, Any]) -> str:
    slug = str(raw.get("slug", ""))
    if not slug.startswith(_HB_PREFIX):
        slug = f"{_HB_PREFIX}{slug}"
    return slug


class HomebrewStore:
    """Validated, disk-persisted homebrew content store."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._entries: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.is_file():
            return
        try:
            raw_file = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to read homebrew store %s: %s", self._path, exc)
            return
        if not isinstance(raw_file, dict):
            logger.warning("Homebrew store %s is malformed (not an object)", self._path)
            return
        for slug, entry in raw_file.items():
            try:
                category = entry["category"]
                raw = entry["raw"]
                parser = _PARSERS[category]
                parser(raw)
            except (KeyError, ValidationError, TypeError) as exc:
                logger.warning("Dropping invalid homebrew entry %r: %s", slug, exc)
                continue
            self._entries[slug] = {"category": category, "raw": raw}

    def _persist(self) -> None:
        tmp_path = self._path.with_suffix(".tmp")
        tmp_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path.write_text(json.dumps(self._entries, indent=2), encoding="utf-8")
        os.replace(tmp_path, self._path)

    def add(self, category: Category, raw: dict[str, Any]) -> str:
        parser = _PARSERS[category]
        slug = _normalize_slug(raw)
        raw = {**raw, "slug": slug}
        try:
            model = parser(raw)
        except ValidationError as exc:
            raise HomebrewValidationError(str(exc)) from exc
        if isinstance(model, BaseModel):
            raw = json.loads(model.model_dump_json())
        self._entries[slug] = {"category": category, "raw": raw}
        self._persist()
        return slug

    def remove(self, slug: str) -> bool:
        if slug not in self._entries:
            return False
        del self._entries[slug]
        self._persist()
        return True

    def entries(self) -> dict[str, dict[str, Any]]:
        return dict(self._entries)

    def as_memory_loader(self) -> MemoryAssetLoader:
        grouped: dict[str, list[Any]] = {category: [] for category in _PARSERS}
        for entry in self._entries.values():
            category = entry["category"]
            parser = _PARSERS[category]
            grouped[category].append(parser(entry["raw"]))
        return MemoryAssetLoader(
            items=grouped["items"],
            monsters=grouped["monsters"],
            spells=grouped["spells"],
            species=grouped["species"],
            classes=grouped["classes"],
            subclasses=grouped["subclasses"],
            backgrounds=grouped["backgrounds"],
            feats=grouped["feats"],
            features=grouped["features"],
        )
