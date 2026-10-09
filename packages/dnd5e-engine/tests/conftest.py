"""Test isolation shared by the whole engine suite."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from dnd5e_engine.lib_loader import set_lib_loader_for_tests


@pytest.fixture(autouse=True)
def _bundled_lib_loader() -> Iterator[None]:
    """Start and end every test on the bundled corpus.

    Many tests install a ``MemoryAssetLoader`` through the process-wide loader
    seam and leave it installed. The reset lives at the root of the test
    package because, given ``tests/e2e`` files, then a ``tests`` file, then
    ``tests/e2e`` files again on one command line, pytest collects
    ``tests/e2e`` twice, and only the first collection carries that
    directory's ``conftest.py`` fixtures.
    """
    set_lib_loader_for_tests(None)
    yield
    set_lib_loader_for_tests(None)
