import pytest


@pytest.fixture(autouse=True)
def _isolated_key_store(tmp_path, monkeypatch):
    """Tests never read or write the real ~/.mavis/keys.json."""
    monkeypatch.setenv("MAVIS_KEYS_FILE", str(tmp_path / "keys.json"))


@pytest.fixture(autouse=True)
def _isolated_usage_files(tmp_path, monkeypatch):
    """Tests never touch the real ~/.mavis/usage.db or audit.log."""
    monkeypatch.setenv("MAVIS_USAGE_DB", str(tmp_path / "usage.db"))
    monkeypatch.setenv("MAVIS_AUDIT_LOG", str(tmp_path / "audit.log"))
