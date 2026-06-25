import pytest
from pathlib import Path

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
