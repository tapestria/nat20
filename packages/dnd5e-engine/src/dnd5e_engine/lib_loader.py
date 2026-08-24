"""Module-level lib AssetLoader singleton for the typed-Activity resolver.

Returns the lib's typed ``AssetLoader`` (``dnd5e_srd_data``); production combat
resolution reads its corpus through this singleton. The prior Avrae loader was
retired in Phase 7b.
"""

from __future__ import annotations

from dnd5e_srd_data.loader import AssetLoader, BundledAssetLoader

_LIB_LOADER: AssetLoader | None = None


def get_lib_loader() -> AssetLoader:
    global _LIB_LOADER
    if _LIB_LOADER is None:
        _LIB_LOADER = BundledAssetLoader()
    return _LIB_LOADER


def set_lib_loader_for_tests(loader: AssetLoader | None) -> None:
    """Inject a loader (MemoryAssetLoader in tests); None reverts to lazy default."""
    global _LIB_LOADER
    _LIB_LOADER = loader


def configure_lib_loader(loader: AssetLoader | None) -> None:
    """Public host seam: install a custom AssetLoader (e.g. a homebrew
    overlay). ``None`` reverts to the lazy bundled default. Hosts must
    call this before start_combat; swapping mid-combat is unsupported."""
    global _LIB_LOADER
    _LIB_LOADER = loader


__all__ = [
    "configure_lib_loader",
    "get_lib_loader",
    "set_lib_loader_for_tests",
]
