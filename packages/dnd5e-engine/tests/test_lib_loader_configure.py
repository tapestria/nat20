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
