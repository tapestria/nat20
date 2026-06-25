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


__all__ = [
    "get_lib_loader",
    "set_lib_loader_for_tests",
]
