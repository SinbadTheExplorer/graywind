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


@pytest.fixture(autouse=True)
def _fresh_lockout():
    """Wrong-key tests must not lock out the tests that run after them."""
    import guards
    guards.LOCKOUT.reset()
    yield
    guards.LOCKOUT.reset()


@pytest.fixture(autouse=True)
def _no_real_alerts(monkeypatch):
    """Tests never post to the owner's ntfy topic."""
    monkeypatch.delenv("MAVIS_NTFY_TOPIC", raising=False)


@pytest.fixture(autouse=True)
def _isolated_report_files(tmp_path, monkeypatch):
    """Johnny Reports state (news, events, briefs, pushes) stays in tmp."""
    for var, name in (("MAVIS_NEWS_FILE", "news.json"), ("MAVIS_EVENTS_FILE", "events.json"),
                      ("MAVIS_WATCH_FILE", "watch.json"), ("MAVIS_SCHEDULE_FILE", "schedule.json"),
                      ("MAVIS_PUSH_FILE", "pushes.json"), ("MAVIS_GRAYWIND_REPO", "graywind-state")):
        monkeypatch.setenv(var, str(tmp_path / name))
