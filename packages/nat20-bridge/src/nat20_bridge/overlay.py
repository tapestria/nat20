"""OverlayAssetLoader — layers a homebrew ``MemoryAssetLoader`` over a base loader.

Canonical entries always win: every ``get_*`` tries ``base`` first, falling
through to ``overlay`` only when the base has no entry for the slug. This
keeps canonical SRD content immutable even if a homebrew slug collides with
a canonical one (the collision case is additionally guarded against at
``HomebrewStore.add`` time via the mandatory ``hb-`` prefix).
"""

from __future__ import annotations

from dnd5e_srd_data.loader import AssetLoader, Category, MemoryAssetLoader
from dnd5e_srd_data.schema.background import Background
from dnd5e_srd_data.schema.class_ import Class, Subclass
from dnd5e_srd_data.schema.condition import Condition
from dnd5e_srd_data.schema.feat import Feat
from dnd5e_srd_data.schema.feature import Feature
from dnd5e_srd_data.schema.item import Armor, Item, MagicItem, Weapon
from dnd5e_srd_data.schema.monster import Monster
from dnd5e_srd_data.schema.species import Species
from dnd5e_srd_data.schema.spell import Spell


class OverlayAssetLoader:
    """Combines a base :class:`AssetLoader` with a homebrew overlay.

    Implements the full ``AssetLoader`` protocol. Base entries are never
    shadowed by overlay entries with the same slug.
    """

    def __init__(self, *, base: AssetLoader, overlay: MemoryAssetLoader) -> None:
        self._base = base
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

    def list_slugs(self, category: Category) -> list[str]:
        base_slugs = self._base.list_slugs(category)
        overlay_slugs = self._overlay.list_slugs(category)
        base_set = set(base_slugs)
        return [*base_slugs, *(s for s in overlay_slugs if s not in base_set)]

    def __contains__(self, key: tuple[Category, str]) -> bool:
        return (key in self._base) or (key in self._overlay)
