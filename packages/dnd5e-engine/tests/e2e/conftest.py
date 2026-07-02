from __future__ import annotations

import pytest
from dnd5e_srd_data.loader import BundledAssetLoader

from dnd5e_engine.lib_loader import set_lib_loader_for_tests


@pytest.fixture(autouse=True)
def _bundled_loader():
    set_lib_loader_for_tests(BundledAssetLoader())
    yield
    set_lib_loader_for_tests(None)
