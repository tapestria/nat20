"""AssetLoader Protocol + in-memory implementation.

Production `BundledAssetLoader` lives below; tests use `MemoryAssetLoader`.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from importlib import resources
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

from dnd5e_srd_data.schema.background import Background
from dnd5e_srd_data.schema.class_ import Class, Subclass
from dnd5e_srd_data.schema.feat import Feat
from dnd5e_srd_data.schema.feature import Feature
from dnd5e_srd_data.schema.item import Armor, Item, MagicItem, Weapon
from dnd5e_srd_data.schema.monster import Monster
from dnd5e_srd_data.schema.species import Species
from dnd5e_srd_data.schema.spell import Spell

Category = Literal[
    "items",
    "monsters",
    "spells",
    "species",
    "classes",
    "subclasses",
    "backgrounds",
    "feats",
    "features",
]

_CATEGORIES: tuple[str, ...] = (
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


@runtime_checkable
class AssetLoader(Protocol):
    def get_item(self, slug: str) -> Item | Weapon | Armor | MagicItem | None: ...
    def get_weapon(self, slug: str) -> Weapon | None: ...
    def get_armor(self, slug: str) -> Armor | None: ...
    def get_monster(self, slug: str) -> Monster | None: ...
    def get_spell(self, slug: str) -> Spell | None: ...
    def get_species(self, slug: str) -> Species | None: ...
    def get_class(self, slug: str) -> Class | None: ...
    def get_subclass(self, slug: str) -> Subclass | None: ...
    def get_background(self, slug: str) -> Background | None: ...
    def get_feat(self, slug: str) -> Feat | None: ...
    def get_feature(self, slug: str) -> Feature | None: ...
    def list_slugs(self, category: Category) -> list[str]: ...
    def __contains__(self, key: tuple[Category, str]) -> bool: ...


class MemoryAssetLoader:
    """In-memory loader for tests. Pass entities at construction."""

    def __init__(
        self,
        *,
        items: Sequence[Item | Weapon | Armor | MagicItem] = (),
        monsters: Sequence[Monster] = (),
        spells: Sequence[Spell] = (),
        species: Sequence[Species] = (),
        classes: Sequence[Class] = (),
        subclasses: Sequence[Subclass] = (),
        backgrounds: Sequence[Background] = (),
        feats: Sequence[Feat] = (),
        features: Sequence[Feature] = (),
    ) -> None:
        self._items: dict[str, Item | Weapon | Armor | MagicItem] = {i.slug: i for i in items}
        self._monsters: dict[str, Monster] = {m.slug: m for m in monsters}
        self._spells: dict[str, Spell] = {s.slug: s for s in spells}
        self._species: dict[str, Species] = {sp.slug: sp for sp in species}
        self._classes: dict[str, Class] = {c.slug: c for c in classes}
        self._subclasses: dict[str, Subclass] = {s.slug: s for s in subclasses}
        self._backgrounds: dict[str, Background] = {b.slug: b for b in backgrounds}
        self._feats: dict[str, Feat] = {f.slug: f for f in feats}
        self._features: dict[str, Feature] = {ft.slug: ft for ft in features}

    def get_item(self, slug: str) -> Item | Weapon | Armor | MagicItem | None:
        return self._items.get(slug)

    def get_weapon(self, slug: str) -> Weapon | None:
        candidate = self._items.get(slug)
        return candidate if isinstance(candidate, Weapon) else None

    def get_armor(self, slug: str) -> Armor | None:
        candidate = self._items.get(slug)
        return candidate if isinstance(candidate, Armor) else None

    def get_monster(self, slug: str) -> Monster | None:
        return self._monsters.get(slug)

    def get_spell(self, slug: str) -> Spell | None:
        return self._spells.get(slug)

    def get_species(self, slug: str) -> Species | None:
        return self._species.get(slug)

    def get_class(self, slug: str) -> Class | None:
        return self._classes.get(slug)

    def get_subclass(self, slug: str) -> Subclass | None:
        return self._subclasses.get(slug)

    def get_background(self, slug: str) -> Background | None:
        return self._backgrounds.get(slug)

    def get_feat(self, slug: str) -> Feat | None:
        return self._feats.get(slug)

    def get_feature(self, slug: str) -> Feature | None:
        return self._features.get(slug)

    def list_slugs(self, category: Category) -> list[str]:
        if category == "items":
            return sorted(self._items)
        if category == "monsters":
            return sorted(self._monsters)
        if category == "spells":
            return sorted(self._spells)
        if category == "species":
            return sorted(self._species)
        if category == "classes":
            return sorted(self._classes)
        if category == "subclasses":
            return sorted(self._subclasses)
        if category == "backgrounds":
            return sorted(self._backgrounds)
        if category == "feats":
            return sorted(self._feats)
        if category == "features":
            return sorted(self._features)
        return []

    def __contains__(self, key: object) -> bool:
        if not (isinstance(key, tuple) and len(key) == 2):
            return False
        category, slug = key
        if category not in _CATEGORIES:
            return False
        return slug in self.list_slugs(category)


class BundledAssetLoader:
    """Reads canonical/<category>/<slug>.json on demand. Lazy per-slug.

    Production: constructed with no args; reads packaged ``canonical/``.
    Tests: pass an explicit ``root`` pointing at a fixture tree.
    """

    def __init__(self, *, root: Path | None = None) -> None:
        self._root: Path | None = root

    def _category_dir(self, category: Category) -> Path:
        if self._root is not None:
            return self._root / category
        # importlib.resources path for packaged canonical/
        return Path(str(resources.files("dnd5e_srd_data") / "canonical" / category))

    def _load_json(self, category: Category, slug: str) -> dict[str, Any] | None:
        path = self._category_dir(category) / f"{slug}.json"
        if not path.is_file():
            return None
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            return None
        return loaded

    def get_item(self, slug: str) -> Item | Weapon | Armor | MagicItem | None:
        raw = self._load_json("items", slug)
        if raw is None:
            return None
        # Explicit ``item_kind`` discriminator is authoritative; canonical
        # always writes it via the schema default. Default to ``"item"`` so
        # any legacy JSON without the field deserializes as a plain Item.
        kind = raw.get("item_kind", "item")
        if kind == "weapon":
            return Weapon.model_validate(raw)
        if kind == "armor":
            return Armor.model_validate(raw)
        if kind == "magic_item":
            return MagicItem.model_validate(raw)
        return Item.model_validate(raw)

    def get_weapon(self, slug: str) -> Weapon | None:
        candidate = self.get_item(slug)
        return candidate if isinstance(candidate, Weapon) else None

    def get_armor(self, slug: str) -> Armor | None:
        candidate = self.get_item(slug)
        return candidate if isinstance(candidate, Armor) else None

    def get_monster(self, slug: str) -> Monster | None:
        raw = self._load_json("monsters", slug)
        if raw is None:
            return None
        return Monster.model_validate(raw)

    def get_spell(self, slug: str) -> Spell | None:
        raw = self._load_json("spells", slug)
        if raw is None:
            return None
        return Spell.model_validate(raw)

    def get_species(self, slug: str) -> Species | None:
        raw = self._load_json("species", slug)
        if raw is None:
            return None
        return Species.model_validate(raw)

    def get_class(self, slug: str) -> Class | None:
        raw = self._load_json("classes", slug)
        if raw is None:
            return None
        return Class.model_validate(raw)

    def get_subclass(self, slug: str) -> Subclass | None:
        raw = self._load_json("subclasses", slug)
        if raw is None:
            return None
        return Subclass.model_validate(raw)

    def get_background(self, slug: str) -> Background | None:
        raw = self._load_json("backgrounds", slug)
        if raw is None:
            return None
        return Background.model_validate(raw)

    def get_feat(self, slug: str) -> Feat | None:
        raw = self._load_json("feats", slug)
        if raw is None:
            return None
        return Feat.model_validate(raw)

    def get_feature(self, slug: str) -> Feature | None:
        raw = self._load_json("features", slug)
        if raw is None:
            return None
        return Feature.model_validate(raw)

    def list_slugs(self, category: Category) -> list[str]:
        d = self._category_dir(category)
        if not d.is_dir():
            return []
        return sorted(p.stem for p in d.glob("*.json"))

    def __contains__(self, key: object) -> bool:
        if not (isinstance(key, tuple) and len(key) == 2):
            return False
        category, slug = key
        if category not in _CATEGORIES:
            return False
        return slug in self.list_slugs(category)
