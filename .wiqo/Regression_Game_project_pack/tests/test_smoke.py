def test_smoke_import():
    import importlib.util
    spec = importlib.util.spec_from_file_location('main', 'src/main.py')
    assert spec is not None