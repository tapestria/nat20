"""AssetLoader Protocol + in-memory implementation.

Production `BundledAssetLoader` lives below; tests use `MemoryAssetLoader`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from importlib import resources
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

from dnd5e_srd_data.schema.background import Background
from dnd5e_srd_data.schema.class_ import Class, Subclass
from dnd5e_srd_data.schema.condition import Condition
from dnd5e_srd_data.schema.feat import Feat
from dnd5e_srd_data.schema.feature import Feature
from dnd5e_srd_data.schema.item import Armor, Item, MagicItem, Weapon
from dnd5e_srd_data.schema.monster import Monster, MonsterTrait
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
    "conditions",
    "traits",
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
    "conditions",
    "traits",
)


@runtime_checkable
class AssetLoader(Protocol):
    def get_item(self, slug: str) -> Item | Weapon | Armor | MagicItem | None: ...
    def get_weapon(self, slug: str) -> Weapon | None: ...
    def get_armor(self, slug: str) -> Armor | None: ...
    def get_monster(self, slug: str) -> Monster | None: ...
    def get_spell(self, slug: str) -> Spell | None: ...
    def get_spell_by_uuid(self, uuid: str) -> Spell | None: ...
    def get_species(self, slug: str) -> Species | None: ...
    def get_class(self, slug: str) -> Class | None: ...
    def get_subclass(self, slug: str) -> Subclass | None: ...
    def get_background(self, slug: str) -> Background | None: ...
    def get_feat(self, slug: str) -> Feat | None: ...
    def get_feature(self, slug: str) -> Feature | None: ...
    def get_condition(self, slug: str) -> Condition | None: ...
    def list_conditions(self) -> list[str]: ...
    def get_trait(self, slug: str) -> MonsterTrait | None: ...
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
        conditions: Sequence[Condition] = (),
        traits: Sequence[MonsterTrait] = (),
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
        self._conditions: dict[str, Condition] = {c.slug: c for c in conditions}
        self._traits: dict[str, MonsterTrait] = {t.slug: t for t in traits}

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

    def get_spell_by_uuid(self, uuid: str) -> Spell | None:
        if not uuid:
            return None
        for slug in self.list_slugs("spells"):
            spell = self.get_spell(slug)
            if spell is not None and spell.foundry_uuid == uuid:
                return spell
        return None

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

    def get_condition(self, slug: str) -> Condition | None:
        return self._conditions.get(slug)

    def list_conditions(self) -> list[str]:
        return sorted(self._conditions)

    def get_trait(self, slug: str) -> MonsterTrait | None:
        return self._traits.get(slug)

    def list_slugs(self, category: Category) -> list[str]:
        by_category: dict[str, Mapping[str, object]] = {
            "items": self._items,
            "monsters": self._monsters,
            "spells": self._spells,
            "species": self._species,
            "classes": self._classes,
            "subclasses": self._subclasses,
            "backgrounds": self._backgrounds,
            "feats": self._feats,
            "features": self._features,
            "conditions": self._conditions,
            "traits": self._traits,
        }
        return sorted(by_category.get(category, {}))

    def __contains__(self, key: object) -> bool:
        if not (isinstance(key, tuple) and len(key) == 2):
            return False
        category, slug = key
        if category not in _CATEGORIES:
            return False
        return slug in self.list_slugs(category)


class OverlayAssetLoader:
    """Combines a base :class:`AssetLoader` with a homebrew overlay.

    Canonical entries always win: every ``get_*`` tries ``base`` first and
    falls through to ``overlay`` only when the base has no entry for the slug.

    Implements the full ``AssetLoader`` protocol. Base entries are never
    shadowed by overlay entries with the same slug.
    """

    def __init__(self, *, base: AssetLoader, overlay: MemoryAssetLoader) -> None:
        self._base = base
        self._overlay = overlay

    def replace_overlay(self, overlay: MemoryAssetLoader) -> None:
        """Swap the homebrew layer in place; the base and this object stay put."""
        self._overlay = overlay

    def get_item(self, slug: str) -> Item | Weapon | Armor | MagicItem | None:
        found = self._base.get_item(slug)
        return found if found is not None else self._overlay.get_item(slug)

    def get_weapon(self, slug: str) -> Weapon | None:
        found = self._base.get_weapon(slug)
        return found if found is not None else self._overlay.get_weapon(slug)

    def get_armor(self, slug: str) -> Armor | None:
        found = self._base.get_armor(slug)
        return found if found is not None else self._overlay.get_armor(slug)

    def get_monster(self, slug: str) -> Monster | None:
        found = self._base.get_monster(slug)
        return found if found is not None else self._overlay.get_monster(slug)

    def get_spell(self, slug: str) -> Spell | None:
        found = self._base.get_spell(slug)
        return found if found is not None else self._overlay.get_spell(slug)

    def get_spell_by_uuid(self, uuid: str) -> Spell | None:
        found = self._base.get_spell_by_uuid(uuid)
        return found if found is not None else self._overlay.get_spell_by_uuid(uuid)

    def get_species(self, slug: str) -> Species | None:
        found = self._base.get_species(slug)
        return found if found is not None else self._overlay.get_species(slug)

    def get_class(self, slug: str) -> Class | None:
        found = self._base.get_class(slug)
        return found if found is not None else self._overlay.get_class(slug)

    def get_subclass(self, slug: str) -> Subclass | None:
        found = self._base.get_subclass(slug)
        return found if found is not None else self._overlay.get_subclass(slug)

    def get_background(self, slug: str) -> Background | None:
        found = self._base.get_background(slug)
        return found if found is not None else self._overlay.get_background(slug)

    def get_feat(self, slug: str) -> Feat | None:
        found = self._base.get_feat(slug)
        return found if found is not None else self._overlay.get_feat(slug)

    def get_feature(self, slug: str) -> Feature | None:
        found = self._base.get_feature(slug)
        return found if found is not None else self._overlay.get_feature(slug)

    def get_condition(self, slug: str) -> Condition | None:
        found = self._base.get_condition(slug)
        return found if found is not None else self._overlay.get_condition(slug)

    def list_conditions(self) -> list[str]:
        return self.list_slugs("conditions")

    def get_trait(self, slug: str) -> MonsterTrait | None:
        found = self._base.get_trait(slug)
        return found if found is not None else self._overlay.get_trait(slug)

    def list_slugs(self, category: Category) -> list[str]:
        base_slugs = self._base.list_slugs(category)
        overlay_slugs = self._overlay.list_slugs(category)
        base_set = set(base_slugs)
        return [*base_slugs, *(s for s in overlay_slugs if s not in base_set)]

    def __contains__(self, key: tuple[Category, str]) -> bool:
        return (key in self._base) or (key in self._overlay)


class BundledAssetLoader:
    """Reads canonical/<category>/<slug>.json on demand. Lazy per-slug.

    Production: constructed with no args; reads packaged ``canonical/``.
    Tests: pass an explicit ``root`` pointing at a fixture tree.
    """

    def __init__(self, *, root: Path | None = None) -> None:
        self._root: Path | None = root
        self._spell_uuid_index: dict[str, str] | None = None

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

    def get_spell_by_uuid(self, uuid: str) -> Spell | None:
        if not uuid:
            return None
        if self._spell_uuid_index is None:
            index: dict[str, str] = {}
            for candidate_slug in self.list_slugs("spells"):
                spell = self.get_spell(candidate_slug)
                if spell is not None and spell.foundry_uuid:
                    index[spell.foundry_uuid] = candidate_slug
            self._spell_uuid_index = index
        resolved_slug = self._spell_uuid_index.get(uuid)
        return self.get_spell(resolved_slug) if resolved_slug is not None else None

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

    def get_condition(self, slug: str) -> Condition | None:
        raw = self._load_json("conditions", slug)
        if raw is None:
            return None
        return Condition.model_validate(raw)

    def list_conditions(self) -> list[str]:
        return self.list_slugs("conditions")

    def get_trait(self, slug: str) -> MonsterTrait | None:
        raw = self._load_json("traits", slug)
        if raw is None:
            return None
        return MonsterTrait.model_validate(raw)

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
