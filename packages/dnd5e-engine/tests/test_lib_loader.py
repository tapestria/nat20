from dnd5e_srd_data.loader import BundledAssetLoader, MemoryAssetLoader

from dnd5e_engine import lib_loader


def test_default_is_bundled_loader():
    lib_loader.set_lib_loader_for_tests(None)
    loader = lib_loader.get_lib_loader()
    assert isinstance(loader, BundledAssetLoader)
    assert loader.get_spell("magic-missile") is not None


def test_set_for_tests_overrides_singleton():
    mem = MemoryAssetLoader()
    lib_loader.set_lib_loader_for_tests(mem)
    assert lib_loader.get_lib_loader() is mem
    lib_loader.set_lib_loader_for_tests(None)
    assert isinstance(lib_loader.get_lib_loader(), BundledAssetLoader)
