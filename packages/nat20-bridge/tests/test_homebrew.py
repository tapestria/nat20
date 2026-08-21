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


def test_add_armor_and_magic_item(tmp_path: Path) -> None:
    store = HomebrewStore(tmp_path / "homebrew.json")
    armor = BundledAssetLoader().get_armor("shield")
    assert armor is not None
    raw_armor = json.loads(armor.model_dump_json())
    raw_armor["slug"] = "hb-shield"
    slug = store.add("items", raw_armor)
    assert slug == "hb-shield"
    assert store.as_memory_loader().get_armor("hb-shield") is not None


def test_add_other_categories(tmp_path: Path) -> None:
    store = HomebrewStore(tmp_path / "homebrew.json")
    loader = BundledAssetLoader()

    monster = loader.get_monster("goblin-warrior")
    assert monster is not None
    raw = json.loads(monster.model_dump_json())
    raw["slug"] = "hb-goblin"
    assert store.add("monsters", raw) == "hb-goblin"

    spell = loader.get_spell("acid-arrow")
    assert spell is not None
    raw = json.loads(spell.model_dump_json())
    raw["slug"] = "hb-acid-arrow"
    assert store.add("spells", raw) == "hb-acid-arrow"

    species = loader.get_species("dwarf")
    assert species is not None
    raw = json.loads(species.model_dump_json())
    raw["slug"] = "hb-dwarf"
    assert store.add("species", raw) == "hb-dwarf"

    klass = loader.get_class("bard")
    assert klass is not None
    raw = json.loads(klass.model_dump_json())
    raw["slug"] = "hb-bard"
    assert store.add("classes", raw) == "hb-bard"

    subclass = loader.get_subclass("champion")
    assert subclass is not None
    raw = json.loads(subclass.model_dump_json())
    raw["slug"] = "hb-champion"
    assert store.add("subclasses", raw) == "hb-champion"

    background = loader.get_background("sage")
    assert background is not None
    raw = json.loads(background.model_dump_json())
    raw["slug"] = "hb-sage"
    assert store.add("backgrounds", raw) == "hb-sage"

    feat = loader.get_feat("alert")
    assert feat is not None
    raw = json.loads(feat.model_dump_json())
    raw["slug"] = "hb-alert"
    assert store.add("feats", raw) == "hb-alert"

    feature = loader.get_feature("action-surge")
    assert feature is not None
    raw = json.loads(feature.model_dump_json())
    raw["slug"] = "hb-action-surge"
    assert store.add("features", raw) == "hb-action-surge"

    mem = store.as_memory_loader()
    assert mem.get_monster("hb-goblin") is not None
    assert mem.get_spell("hb-acid-arrow") is not None
    assert mem.get_species("hb-dwarf") is not None
    assert mem.get_class("hb-bard") is not None
    assert mem.get_subclass("hb-champion") is not None
    assert mem.get_background("hb-sage") is not None
    assert mem.get_feat("hb-alert") is not None
    assert mem.get_feature("hb-action-surge") is not None


def test_entries_returns_slug_to_category_and_raw(tmp_path: Path) -> None:
    store = HomebrewStore(tmp_path / "homebrew.json")
    slug = store.add("items", _raw_weapon())
    entries = store.entries()
    assert set(entries) == {slug}
    assert entries[slug]["category"] == "items"
    assert entries[slug]["raw"]["slug"] == slug


def test_load_drops_invalid_entries_and_warns(tmp_path: Path) -> None:
    path = tmp_path / "homebrew.json"
    path.write_text(
        json.dumps(
            {
                "hb-junk": {"category": "items", "raw": {"slug": "hb-junk", "item_kind": "weapon"}},
                "hb-bad-category": {"category": "not-a-category", "raw": {}},
                "hb-missing-raw": {"category": "items"},
            }
        ),
        encoding="utf-8",
    )
    store = HomebrewStore(path)
    assert store.entries() == {}


def test_load_ignores_unreadable_file(tmp_path: Path) -> None:
    path = tmp_path / "homebrew.json"
    path.write_text("not json{", encoding="utf-8")
    store = HomebrewStore(path)
    assert store.entries() == {}


def test_load_ignores_non_object_file(tmp_path: Path) -> None:
    path = tmp_path / "homebrew.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    store = HomebrewStore(path)
    assert store.entries() == {}
