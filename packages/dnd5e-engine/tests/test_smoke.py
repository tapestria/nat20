"""Phase 2 smoke test — package imports and exposes a version string."""

import dnd5e_engine


def test_package_imports() -> None:
    assert isinstance(dnd5e_engine.__version__, str)
    assert dnd5e_engine.__version__
