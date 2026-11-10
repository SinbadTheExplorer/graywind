import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

import auth


def make_app():
    app = FastAPI()

    @app.get("/protected")
    def protected(api_key: str = Depends(auth.require_api_key)):
        return {"ok": True}

    return app


def test_missing_key_is_rejected(monkeypatch):
    monkeypatch.setattr(auth, "MAVIS_API_KEY", "secret123")
    client = TestClient(make_app())

    resp = client.get("/protected")

    assert resp.status_code == 401


def test_wrong_key_is_rejected(monkeypatch):
    monkeypatch.setattr(auth, "MAVIS_API_KEY", "secret123")
    client = TestClient(make_app())

    resp = client.get("/protected", headers={"X-API-Key": "wrong"})

    assert resp.status_code == 401


def test_correct_key_is_accepted(monkeypatch):
    monkeypatch.setattr(auth, "MAVIS_API_KEY", "secret123")
    client = TestClient(make_app())

    resp = client.get("/protected", headers={"X-API-Key": "secret123"})

    assert resp.status_code == 200


def test_unset_server_key_fails_closed(monkeypatch):
    monkeypatch.setattr(auth, "MAVIS_API_KEY", None)
    client = TestClient(make_app())

    resp = client.get("/protected", headers={"X-API-Key": "anything"})

    assert resp.status_code == 500


def test_non_ascii_key_is_rejected_cleanly_not_a_server_error(monkeypatch):
    # A real server decodes raw header bytes as latin-1 and can hand this
    # function a non-ASCII str; httpx's TestClient refuses to send one as a
    # plain header value, so this calls the dependency directly.
    monkeypatch.setattr(auth, "MAVIS_API_KEY", "secret123")

    with pytest.raises(HTTPException) as exc_info:
        auth.require_api_key(x_api_key="sécret")

    assert exc_info.value.status_code == 401


def test_require_api_key_returns_record(monkeypatch):
    monkeypatch.setattr(auth, "MAVIS_API_KEY", "secret123")
    rec = auth.require_api_key(x_api_key="secret123")
    assert rec.id == "owner-env" and rec.scope == "owner"


def test_file_key_returns_its_own_scope(monkeypatch):
    import keys
    monkeypatch.setattr(auth, "MAVIS_API_KEY", "secret123")
    guest = keys.add("friend", "guest")
    assert auth.require_api_key(x_api_key=guest).scope == "guest"


def test_file_keys_alone_make_the_server_configured(monkeypatch):
    import keys
    monkeypatch.setattr(auth, "MAVIS_API_KEY", None)
    guest = keys.add("friend", "guest")
    assert auth.require_api_key(x_api_key=guest).id == "friend"
    with pytest.raises(HTTPException) as exc_info:
        auth.require_api_key(x_api_key="wrong")
    assert exc_info.value.status_code == 401


def test_revoked_file_key_is_rejected(monkeypatch):
    import keys
    monkeypatch.setattr(auth, "MAVIS_API_KEY", "secret123")
    guest = keys.add("friend", "guest")
    keys.revoke("friend")
    with pytest.raises(HTTPException) as exc_info:
        auth.require_api_key(x_api_key=guest)
    assert exc_info.value.status_code == 401


def test_env_key_honours_rate_limit_setting(monkeypatch):
    import rate_limit
    monkeypatch.setattr(auth, "MAVIS_API_KEY", "secret123")
    monkeypatch.setattr(rate_limit, "MAX_REQUESTS_PER_WINDOW", 5)
    assert auth.lookup("secret123").per_minute == 5


def test_corrupt_key_file_does_not_lock_out_env_owner(monkeypatch, tmp_path):
    import os
    from pathlib import Path
    monkeypatch.setattr(auth, "MAVIS_API_KEY", "secret123")
    Path(os.environ["MAVIS_KEYS_FILE"]).write_text("garbage", encoding="utf-8")
    assert auth.require_api_key(x_api_key="secret123").id == "owner-env"


def test_still_valid_follows_revoke(monkeypatch):
    import keys
    monkeypatch.setattr(auth, "MAVIS_API_KEY", "secret123")
    guest = keys.add("friend", "guest")
    rec = auth.lookup(guest)
    assert auth.still_valid(rec)
    keys.revoke("friend")
    assert not auth.still_valid(rec)
    assert auth.still_valid(auth.lookup("secret123"))
