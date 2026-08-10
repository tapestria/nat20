from pathlib import Path

import pytest

from dnd5e_srd_data import BundledAssetLoader, Monster, Weapon

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "canonical"


@pytest.fixture
def loader() -> BundledAssetLoader:
    return BundledAssetLoader(root=FIXTURE_ROOT)


def test_bundled_loader_finds_monster_in_fixture_tree(loader: BundledAssetLoader):
    m = loader.get_monster("test-goblin")
    assert isinstance(m, Monster)
    assert m.name == "Test Goblin"


def test_bundled_loader_returns_none_for_unknown(loader: BundledAssetLoader):
    assert loader.get_monster("nonexistent") is None


def test_bundled_loader_finds_weapon(loader: BundledAssetLoader):
    w = loader.get_weapon("test-longsword")
    assert isinstance(w, Weapon)
    assert w.name == "Test Longsword"


def test_bundled_loader_lists_slugs(loader: BundledAssetLoader):
    assert "test-goblin" in loader.list_slugs("monsters")
    assert "test-longsword" in loader.list_slugs("items")


def test_bundled_get_spell_by_uuid():
    loader = BundledAssetLoader()
    spell = loader.get_spell("lightning-bolt")
    assert spell is not None
    assert spell.foundry_uuid
    assert loader.get_spell_by_uuid(spell.foundry_uuid) is not None
    assert loader.get_spell_by_uuid(spell.foundry_uuid).slug == "lightning-bolt"
    assert loader.get_spell_by_uuid("Compendium.dnd5e.spells24.Item.missing") is None


# Known legacy-pack cast reference: rod-of-alertness delegates to the 2014
# "spells" compendium, which the SRD 5.2 corpus does not carry. Tracked as
# upstream data debt — every other cast uuid must resolve.
_KNOWN_UNRESOLVABLE_CAST_UUIDS = {"Compendium.dnd5e.spells.Item.Mzh95utKDPIrjiH8"}


def test_every_item_cast_uuid_resolves_against_spell_corpus():
    loader = BundledAssetLoader()
    unresolved: dict[str, str] = {}
    for slug in loader.list_slugs("items"):
        item = loader.get_item(slug)
        assert item is not None
        for activity in item.activities:
            uuid = getattr(getattr(activity, "spell", None), "uuid", "")
            if not uuid or uuid in _KNOWN_UNRESOLVABLE_CAST_UUIDS:
                continue
            if loader.get_spell_by_uuid(uuid) is None:
                unresolved[slug] = uuid
    assert unresolved == {}
