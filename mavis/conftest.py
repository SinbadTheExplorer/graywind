import pytest


@pytest.fixture(autouse=True)
def _isolated_key_store(tmp_path, monkeypatch):
    """Tests never read or write the real ~/.mavis/keys.json."""
    monkeypatch.setenv("MAVIS_KEYS_FILE", str(tmp_path / "keys.json"))
