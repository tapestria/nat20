"""The asset-loader seam — where the engine gets its rules content.

The engine ships no rules data. Every typed entity it resolves is fetched
through the process-wide ``AssetLoader`` returned by ``get_lib_loader``, which
defaults to the bundled SRD 5.2 corpus (``BundledAssetLoader``).

The engine is edition-agnostic: it resolves whatever typed content it is handed.
To drive it from a different corpus, implement the ``AssetLoader`` protocol and
install it once at startup with ``configure_lib_loader``; pass ``None`` to
revert to the bundled corpus. Install it before opening any combat.
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
