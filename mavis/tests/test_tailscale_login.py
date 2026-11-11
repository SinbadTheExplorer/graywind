"""Sign-in by Tailscale login: no key needed for the owner or a linked guest,
and only for requests relayed by the local `tailscale serve`."""
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import app as app_module
import auth
import call_route
import keys
import rate_limit

OWNER = "me@example.com"
GUEST = "friend@example.com"


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    monkeypatch.setattr(auth, "MAVIS_API_KEY", "secret123")
    monkeypatch.setattr(auth, "OWNER_LOGINS", {OWNER})
    monkeypatch.setattr(auth, "SIGNIN", True)
    monkeypatch.setattr(call_route, "_call_voice", lambda: (None, None))
    monkeypatch.setattr(call_route, "_call_canned",
                        lambda moment: b"GREETING" if moment == "greeting" else None)
    rate_limit._request_log.clear()


def _via_serve():
    """Requests as `tailscale serve` relays them: from localhost."""
    return TestClient(app_module.app, client=("127.0.0.1", 50000))


def _as(login):
    return {"Tailscale-User-Login": login}


def test_owner_login_needs_no_key():
    assert _via_serve().get("/johnny/check", headers=_as(OWNER)).status_code == 200


def test_login_is_case_insensitive():
    assert _via_serve().get("/johnny/check", headers=_as("Me@Example.COM")).status_code == 200


def test_unknown_login_still_needs_a_key():
    assert _via_serve().get("/johnny/check", headers=_as("stranger@x.com")).status_code == 401


def test_login_header_from_anywhere_but_localhost_is_ignored():
    direct = TestClient(app_module.app, client=("100.64.0.9", 50000))
    assert direct.get("/johnny/check", headers=_as(OWNER)).status_code == 401


def test_a_sent_key_always_decides():
    # A wrong key is a wrong key, even from a recognised login -- and it counts.
    resp = _via_serve().get("/johnny/check", headers={**_as(OWNER), "X-API-Key": "nope"})
    assert resp.status_code == 401


def test_linked_guest_login_gets_guest_scope_and_no_keanu():
    keys.add("friend", "guest")
    keys.link("friend", GUEST)
    c = _via_serve()
    assert c.get("/johnny/check", headers=_as(GUEST)).status_code == 200
    assert c.get("/johnny/model.glb", headers=_as(GUEST)).status_code in (403, 404)


def test_unlinked_or_revoked_guest_login_is_refused():
    keys.add("friend", "guest")
    keys.link("friend", GUEST)
    keys.unlink("friend")
    assert _via_serve().get("/johnny/check", headers=_as(GUEST)).status_code == 401
    keys.link("friend", GUEST)
    keys.revoke("friend")
    assert _via_serve().get("/johnny/check", headers=_as(GUEST)).status_code == 401


def test_one_login_links_to_one_key():
    keys.add("a", "guest")
    keys.add("b", "guest")
    keys.link("a", GUEST)
    with pytest.raises(ValueError):
        keys.link("b", GUEST.upper())


def test_signin_is_off_unless_switched_on(monkeypatch):
    monkeypatch.setattr(auth, "SIGNIN", False)
    assert _via_serve().get("/johnny/check", headers=_as(OWNER)).status_code == 401


def test_unlinking_ends_a_login_session():
    keys.add("friend", "guest")
    keys.link("friend", GUEST)
    rec = auth.lookup_login(GUEST)
    assert rec.via_login == GUEST and auth.still_valid(rec)
    keys.unlink("friend")
    assert not auth.still_valid(rec)


def test_owner_login_session_ends_when_owner_login_removed(monkeypatch):
    rec = auth.lookup_login(OWNER)
    assert auth.still_valid(rec)
    monkeypatch.setattr(auth, "OWNER_LOGINS", set())
    assert not auth.still_valid(rec)


def test_a_revoked_holder_gives_its_login_up():
    keys.add("old", "guest")
    keys.link("old", GUEST)
    keys.revoke("old")
    keys.add("new", "guest")
    keys.link("new", GUEST)
    assert auth.lookup_login(GUEST).id == "new"
    with pytest.raises(ValueError):
        keys.link("old", "other@example.com")    # can't link a revoked key


def test_a_null_login_in_the_file_keeps_the_key_working():
    import json
    key = keys.add("friend", "guest")
    path = keys.store_path()
    data = json.loads(path.read_text())
    data["keys"][0]["login"] = None
    path.write_text(json.dumps(data))
    assert auth.lookup(key).id == "friend"


def test_call_start_audit_names_the_login(tmp_path):
    import json
    with _via_serve().websocket_connect("/call", headers=_as(OWNER)) as ws:
        ws.send_json({"type": "hello", "key": None})
        ws.receive_json(); ws.receive_bytes(); ws.receive_json()
        ws.send_json({"type": "end"})
    events = [json.loads(l) for l in (tmp_path / "audit.log").read_text().splitlines()]
    start = next(e for e in events if e["event"] == "call_start")
    assert start["ident"] == f"ts:{OWNER}"


def test_side_jobs_are_kept_off_localhost():
    from pathlib import Path
    deploy = Path(__file__).resolve().parents[2] / "deploy"
    for unit in ("graywind-sync.service", "mavis-alert@.service"):
        assert "IPAddressDeny=localhost" in (deploy / unit).read_text(), unit
    assert "MAVIS_TAILSCALE_SIGNIN=1" in (deploy / "mavis.service").read_text()


@pytest.mark.parametrize("bad", ["", "   ", "a b@x.com", "x\n@y.com", "a" * 200])
def test_bad_logins_are_rejected(bad):
    keys.add("a", "guest")
    with pytest.raises(ValueError):
        keys.link("a", bad)


def test_locked_out_guest_login_is_refused_but_owner_login_is_not():
    import guards
    keys.add("friend", "guest")
    keys.link("friend", GUEST)
    for _ in range(5):
        guards.LOCKOUT.fail("ts:" + GUEST)
        guards.LOCKOUT.fail("ts:" + OWNER)
    c = _via_serve()
    assert c.get("/johnny/check", headers=_as(GUEST)).status_code == 429
    assert c.get("/johnny/check", headers=_as(OWNER)).status_code == 200


def test_call_with_no_key_by_owner_login():
    with _via_serve().websocket_connect("/call", headers=_as(OWNER)) as ws:
        ws.send_json({"type": "hello", "key": None})
        assert ws.receive_json() == {"type": "state", "state": "speaking"}
        assert ws.receive_bytes() == b"GREETING"
        ws.receive_json()
        ws.send_json({"type": "end"})


def test_call_with_no_key_and_no_login_is_refused():
    with _via_serve().websocket_connect("/call") as ws:
        ws.send_json({"type": "hello", "key": None})
        ws.receive_json()
        with pytest.raises(WebSocketDisconnect) as info:
            ws.receive_json()
    assert info.value.code == call_route.CLOSE_WRONG_KEY


def test_keys_file_with_login_field_still_loads(tmp_path):
    keys.add("friend", "guest")
    keys.link("friend", GUEST)
    assert [r.id for r in keys.list_records()] == ["friend"]
    assert keys.lookup_file_login(GUEST).scope == "guest"
