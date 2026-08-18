def test_package_imports() -> None:
    import nat20_demo

    assert nat20_demo.__all__ == []
