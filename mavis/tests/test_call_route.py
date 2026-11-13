"""The /call WebSocket's door: the key check, and that a call reaches run_call."""
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import app as app_module
import auth
import call_route
import rate_limit


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    monkeypatch.setattr(auth, "MAVIS_API_KEY", "secret123")
    monkeypatch.setattr(call_route, "_call_voice", lambda: (None, None))
    monkeypatch.setattr(call_route, "_call_canned",
                        lambda moment: b"GREETING" if moment == "greeting" else None)
    rate_limit._request_log.clear()


def _client():
    return TestClient(app_module.app)


def _wav(seconds=1.0, extra=b""):
    """A real 16 kHz mono 16-bit WAV, as the call page sends."""
    import struct
    n = int(seconds * 32000)
    return (b"RIFF" + struct.pack("<I", 36 + n) + b"WAVE"
            + b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, 16000, 32000, 2, 16)
            + b"data" + struct.pack("<I", n) + b"\x01\x00" * (n // 2) + extra)


def test_wrong_key_is_refused():
    with _client().websocket_connect("/call") as ws:
        ws.send_json({"type": "hello", "key": "nope"})
        assert ws.receive_json() == {"type": "error", "message": "wrong or missing key"}
        with pytest.raises(WebSocketDisconnect) as info:
            ws.receive_json()
    assert info.value.code == call_route.CLOSE_WRONG_KEY


def test_missing_hello_is_refused():
    with _client().websocket_connect("/call") as ws:
        ws.send_text("not json")
        with pytest.raises(WebSocketDisconnect) as info:
            ws.receive_json()
    assert info.value.code == call_route.CLOSE_NO_HELLO


def test_right_key_gets_the_greeting_and_can_hang_up():
    with _client().websocket_connect("/call") as ws:
        ws.send_json({"type": "hello", "key": "secret123"})
        assert ws.receive_json() == {"type": "state", "state": "speaking"}
        assert ws.receive_bytes() == b"GREETING"
        assert ws.receive_json() == {"type": "state", "state": "listening"}
        ws.send_json({"type": "end"})
        assert ws.receive_json() == {"type": "bye"}


def test_unset_server_key_says_so(monkeypatch):
    monkeypatch.setattr(auth, "MAVIS_API_KEY", None)
    with _client().websocket_connect("/call") as ws:
        ws.send_json({"type": "hello", "key": "anything"})
        assert ws.receive_json() == {"type": "error",
                                     "message": "no keys configured on the server"}


def test_rate_limit_is_checked_before_paid_speech_to_text(monkeypatch):
    import asyncio
    import call
    sent = []

    async def fake_stt(wav):
        sent.append(wav)
        return "hi"

    monkeypatch.setattr(call_route.avatar_stt, "transcribe_wav", fake_stt)
    monkeypatch.setattr(auth, "MAVIS_API_KEY", "secret123")
    monkeypatch.setattr(rate_limit, "MAX_REQUESTS_PER_WINDOW", 1)
    rec = auth.lookup("secret123")
    assert asyncio.run(call_route._call_transcribe(rec, _wav(1.0))) == "hi"
    with pytest.raises(call.AnswerError):
        asyncio.run(call_route._call_transcribe(rec, _wav(2.0)))
    assert len(sent) == 1


def test_hello_does_not_use_a_rate_limit_slot():
    with _client().websocket_connect("/call") as ws:
        ws.send_json({"type": "hello", "key": "secret123"})
        ws.receive_json()
    assert not any(rate_limit._request_log.values())


def test_call_page_is_served():
    resp = _client().get("/johnny")
    assert resp.status_code == 200
    assert "<title>Call Johnny</title>" in resp.text


def test_model_needs_the_key(tmp_path, monkeypatch):
    model = tmp_path / "m.glb"
    model.write_bytes(b"glTF")
    monkeypatch.setattr(call_route, "MODEL", model)
    assert _client().get("/johnny/model.glb").status_code == 401
    resp = _client().get("/johnny/model.glb", headers={"X-API-Key": "secret123"})
    assert resp.status_code == 200 and resp.content == b"glTF"
    assert resp.headers["cache-control"] == "private, no-cache"


def test_key_check_endpoint():
    assert _client().get("/johnny/check").status_code == 401
    assert _client().get("/johnny/check", headers={"X-API-Key": "secret123"}).json() == {"ok": True}


def test_three_js_is_served_locally():
    resp = _client().get("/johnny/vendor/three/build/three.module.js")
    assert resp.status_code == 200 and "REVISION = '160'" in resp.text


def test_revoked_key_mid_call_gets_no_paid_stt(monkeypatch):
    import asyncio
    import call
    import keys
    sent = []

    async def fake_stt(wav):
        sent.append(wav)
        return "hi"

    monkeypatch.setattr(call_route.avatar_stt, "transcribe_wav", fake_stt)
    guest = keys.add("friend", "guest")
    rec = auth.lookup(guest)
    assert asyncio.run(call_route._call_transcribe(rec, _wav(1.0))) == "hi"
    keys.revoke("friend")
    with pytest.raises(call.AnswerError):
        asyncio.run(call_route._call_transcribe(rec, _wav(2.0)))
    assert len(sent) == 1



def _stt_spy(monkeypatch):
    sent = []

    async def fake_stt(wav):
        sent.append(wav)
        return "hi"

    monkeypatch.setattr(call_route.avatar_stt, "transcribe_wav", fake_stt)
    return sent


def _owner():
    return auth.lookup("secret123")


@pytest.mark.parametrize("payload", [b"x" * 2_000_000, b"not a wav at all",
                                     _wav(35.0)])
def test_bad_audio_never_reaches_paid_stt(monkeypatch, payload):
    import asyncio
    import call
    import usage
    sent = _stt_spy(monkeypatch)
    with pytest.raises(call.AnswerError):
        asyncio.run(call_route._call_transcribe(_owner(), payload))
    assert sent == []
    assert usage.today_totals()["stt_seconds"] == 0


def test_too_long_says_so_in_character(monkeypatch):
    import asyncio
    import call
    _stt_spy(monkeypatch)
    with pytest.raises(call.AnswerError) as info:
        asyncio.run(call_route._call_transcribe(_owner(), _wav(31.0)))
    assert "under 30 seconds" in str(info.value)


def test_stt_receives_only_the_measured_audio(monkeypatch):
    import asyncio
    import struct
    sent = _stt_spy(monkeypatch)
    trailing = b"LIST" + struct.pack("<I", 5000) + b"\x00" * 5000
    asyncio.run(call_route._call_transcribe(_owner(), _wav(1.0, extra=trailing)))
    assert len(sent[0]) == 44 + 32000


def test_over_stt_cap_is_tapped_out_with_no_stt_call(monkeypatch):
    import asyncio
    import call
    import usage
    sent = _stt_spy(monkeypatch)
    owner = _owner()
    usage.record(owner, "stt_seconds", owner.per_day_stt_seconds - 0.5)
    with pytest.raises(call.AnswerError) as info:
        asyncio.run(call_route._call_transcribe(owner, _wav(1.0)))
    assert "tapped out" in str(info.value)
    assert sent == []


def test_stt_seconds_are_charged_and_failed_stt_refunded(monkeypatch):
    import asyncio
    import usage

    async def broken(wav):
        raise RuntimeError("groq down")

    _stt_spy(monkeypatch)
    asyncio.run(call_route._call_transcribe(_owner(), _wav(2.0)))
    assert usage.today_totals("owner-env")["stt_seconds"] == pytest.approx(2.0)
    monkeypatch.setattr(call_route.avatar_stt, "transcribe_wav", broken)
    with pytest.raises(RuntimeError):
        asyncio.run(call_route._call_transcribe(_owner(), _wav(3.0)))
    assert usage.today_totals("owner-env")["stt_seconds"] == pytest.approx(2.0)


def test_guest_never_gets_graywind_context(monkeypatch):
    # Review Focus 2: however it is worded, a guest's question never even
    # looks at Graywind's facts.
    import asyncio
    import graywind_grounding
    import keys

    def must_not_run(*a, **k):
        raise AssertionError("Graywind facts retrieved for a guest")

    async def fake_stream(query, context=None, **k):
        yield "ok"

    monkeypatch.setattr(graywind_grounding, "retrieve", must_not_run)
    monkeypatch.setattr(app_module, "groq_stream", fake_stream)
    guest = auth.lookup(keys.add("friend", "guest"))

    async def run(q):
        return [e async for e in app_module._answer_events(q, 200, guest)]

    for q in ["what's pending?", "what am I holding?", "graywind watchlist"]:
        events = asyncio.run(run(q))
        assert all("citations" not in e or not any(
            c.get("source") == "graywind" for c in e["citations"]) for e in events)


def test_guest_ask_route_also_skips_graywind(monkeypatch):
    import graywind_grounding
    import keys

    def must_not_run(*a, **k):
        raise AssertionError("Graywind facts retrieved for a guest")

    async def fake_answer(*a, **k):
        return "ok"

    monkeypatch.setattr(graywind_grounding, "retrieve", must_not_run)
    monkeypatch.setattr(app_module, "groq_answer", fake_answer)
    guest = keys.add("friend", "guest")
    resp = _client().post("/ask", json={"query": "what's pending in graywind?"},
                          headers={"X-API-Key": guest})
    assert resp.status_code == 200
    assert resp.json()["citations"] == []


def test_owner_still_gets_graywind_context(monkeypatch):
    import asyncio
    import graywind_grounding
    called = []

    def spy(q, *a, **k):
        called.append(q)
        return []

    async def fake_stream(query, context=None, **k):
        yield "ok"

    monkeypatch.setattr(graywind_grounding, "retrieve", spy)
    monkeypatch.setattr(app_module, "groq_stream", fake_stream)

    async def run():
        return [e async for e in app_module._answer_events("the watchlist", 200, _owner())]

    asyncio.run(run())
    assert called == ["the watchlist"]


def test_guest_model_403_owner_200(monkeypatch, tmp_path):
    import keys
    fake = tmp_path / "keanu.glb"
    fake.write_bytes(b"glTF-fake")
    monkeypatch.setattr(call_route, "MODEL", fake)
    guest = keys.add("friend", "guest")
    c = _client()
    assert c.get("/johnny/model.glb", headers={"X-API-Key": "secret123"}).status_code == 200
    # No public model yet: 404, and the page shows the orb.
    assert c.get("/johnny/model.glb", headers={"X-API-Key": guest}).status_code == 404
    # Even if the public model is pointed at Keanu by mistake.
    monkeypatch.setattr(call_route, "PUBLIC_MODEL", str(fake))
    assert c.get("/johnny/model.glb", headers={"X-API-Key": guest}).status_code == 403
    public = tmp_path / "public.glb"
    public.write_bytes(b"glTF-public")
    monkeypatch.setattr(call_route, "PUBLIC_MODEL", str(public))
    resp = c.get("/johnny/model.glb", headers={"X-API-Key": guest})
    assert resp.status_code == 200 and resp.content == b"glTF-public"


def test_bad_origin_is_told_why_and_closed_4403():
    with _client().websocket_connect(
            "/call", headers={"origin": "https://evil.example"}) as ws:
        assert ws.receive_json() == {"type": "error",
                                     "message": "This page can't call Johnny."}
        with pytest.raises(WebSocketDisconnect) as info:
            ws.receive_json()
    assert info.value.code == call_route.CLOSE_BAD_ORIGIN


def test_allowed_origins_setting_and_forwarded_host_list(monkeypatch):
    class FakeWS:
        def __init__(self, headers): self.headers = headers
    ok = call_route._origin_ok
    assert ok(FakeWS({"origin": "https://johnny.ts.net", "host": "127.0.0.1:8000",
                      "x-forwarded-host": "proxy.local, johnny.ts.net"}))
    assert not ok(FakeWS({"origin": "https://evil.example", "host": "127.0.0.1:8000"}))
    monkeypatch.setattr(call_route, "ALLOWED_ORIGINS", {"https://johnny.ts.net"})
    assert ok(FakeWS({"origin": "https://johnny.ts.net/", "host": "127.0.0.1:8000"}))


def test_own_origin_is_allowed():
    with _client().websocket_connect(
            "/call", headers={"origin": "http://testserver"}) as ws:
        ws.send_json({"type": "hello", "key": "secret123"})
        assert ws.receive_json() == {"type": "state", "state": "speaking"}
        ws.receive_bytes()
        ws.receive_json()
        ws.send_json({"type": "end"})


def test_second_concurrent_call_same_key_is_busy():
    c = _client()
    with c.websocket_connect("/call") as first:
        first.send_json({"type": "hello", "key": "secret123"})
        first.receive_json()
        with c.websocket_connect("/call") as second:
            second.send_json({"type": "hello", "key": "secret123"})
            assert second.receive_json() == {"type": "error",
                                             "message": "Johnny's on another call."}
            with pytest.raises(WebSocketDisconnect) as info:
                second.receive_json()
            assert info.value.code == call_route.CLOSE_BUSY
        first.receive_bytes()
        first.receive_json()
        first.send_json({"type": "end"})
        assert first.receive_json() == {"type": "bye"}
    # The slot is free again afterwards.
    assert call_route.guards.SLOTS.acquire("owner-env")
    call_route.guards.SLOTS.release("owner-env")


def test_call_start_and_end_are_audited():
    import json
    import os
    from pathlib import Path
    with _client().websocket_connect("/call") as ws:
        ws.send_json({"type": "hello", "key": "secret123"})
        ws.receive_json(); ws.receive_bytes(); ws.receive_json()
        ws.send_json({"type": "end"})
        ws.receive_json()
    lines = [json.loads(l) for l in Path(os.environ["MAVIS_AUDIT_LOG"]).read_text().splitlines()]
    events = [(l["event"], l.get("reason")) for l in lines]
    assert ("call_start", None) in events and ("call_end", "end") in events



def test_revoked_key_hello_is_4401():
    import keys
    guest = keys.add("friend", "guest")
    keys.revoke("friend")
    with _client().websocket_connect("/call") as ws:
        ws.send_json({"type": "hello", "key": guest})
        assert ws.receive_json() == {"type": "error", "message": "wrong or missing key"}
        with pytest.raises(WebSocketDisconnect) as info:
            ws.receive_json()
    assert info.value.code == call_route.CLOSE_WRONG_KEY


def test_owner_gets_through_when_guests_fill_every_slot():
    slots = call_route.guards.SLOTS
    assert slots.acquire("g1") and slots.acquire("g2")
    try:
        assert not slots.acquire("g3")             # a third guest waits
        assert slots.acquire("owner-env", owner=True)
        slots.release("owner-env")
    finally:
        slots.release("g1"); slots.release("g2")


def test_cap_hit_mid_answer_finishes_then_refuses_next(monkeypatch):
    # Review Focus 3: the answer in progress completes; the next is refused.
    import asyncio
    import call
    import usage
    owner = _owner()
    usage.record(owner, "llm", owner.per_day_llm - 1)    # one answer left

    async def fake_stream(query, context=None, **k):
        usage.record(owner, "llm", 5)    # someone else uses the rest meanwhile
        yield "First part. "
        yield "Second part."

    monkeypatch.setattr(app_module, "groq_stream", fake_stream)
    deps = call_route._call_deps(owner)

    async def answer(q):
        return [t async for t in deps.answer(q)]

    assert asyncio.run(answer("what is the capital of France")) == [
        "First part. ", "Second part."]
    with pytest.raises(call.AnswerError) as info:
        asyncio.run(answer("and of Spain"))
    assert "tapped out" in str(info.value)


def test_guest_is_refused_on_project_questions_even_with_context(monkeypatch):
    import asyncio
    import graywind_grounding
    import grounding
    import keys

    def must_not_run(*a, **k):
        raise AssertionError("model called for a guest's project question")

    monkeypatch.setattr(grounding, "retrieve",
                        lambda q, *a, **k: [{"id": "x", "label": "Yield Curve"}])
    monkeypatch.setattr(grounding, "format_context", lambda hits: "some bullion fact")
    monkeypatch.setattr(app_module, "groq_stream", must_not_run)
    guest = auth.lookup(keys.add("friend", "guest"))
    q = "what's graywind's tier pool doing"
    assert graywind_grounding.names_project_internals(q)

    async def run():
        return [e async for e in app_module._answer_events(q, 200, guest)]

    events = asyncio.run(run())
    assert events[0] == {"delta": graywind_grounding.UNGROUNDED}


def test_broken_audit_log_does_not_break_calls(monkeypatch):
    import usage

    def broken(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(usage, "audit", broken)
    with _client().websocket_connect("/call") as ws:
        ws.send_json({"type": "hello", "key": "secret123"})
        assert ws.receive_json() == {"type": "state", "state": "speaking"}
        ws.receive_bytes(); ws.receive_json()
        ws.send_json({"type": "end"})
        assert ws.receive_json() == {"type": "bye"}


def test_broken_audit_after_charge_still_refunds(monkeypatch):
    import asyncio
    import usage
    sent = _stt_spy(monkeypatch)

    def broken(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(usage, "audit", broken)
    assert asyncio.run(call_route._call_transcribe(_owner(), _wav(1.0))) == "hi"
    assert len(sent) == 1


def test_junk_frames_use_rate_limit_slots(monkeypatch):
    import asyncio
    import call
    _stt_spy(monkeypatch)
    monkeypatch.setattr(rate_limit, "MAX_REQUESTS_PER_WINDOW", 2)
    for _ in range(2):
        with pytest.raises(call.AnswerError) as info:
            asyncio.run(call_route._call_transcribe(_owner(), b"junk"))
        assert "line dropped" in str(info.value)
    with pytest.raises(call.AnswerError) as info:
        asyncio.run(call_route._call_transcribe(_owner(), b"junk"))
    assert "rate limit" in str(info.value)


# --- Failed-key lockout ---

def _wrong_hello(client, key="nope"):
    with client.websocket_connect("/call") as ws:
        ws.send_json({"type": "hello", "key": key})
        ws.receive_json()
        with pytest.raises(WebSocketDisconnect) as info:
            ws.receive_json()
    return info.value.code


def _guest_key():
    import keys
    return keys.add("friend", "guest")


def test_ws_hello_failures_count():
    client = _client()
    guest = _guest_key()
    assert [_wrong_hello(client) for _ in range(5)] == [call_route.CLOSE_WRONG_KEY] * 5
    with client.websocket_connect("/call") as ws:
        ws.send_json({"type": "hello", "key": guest})
        assert ws.receive_json() == {"type": "error", "message": auth.LOCKED_OUT}
        with pytest.raises(WebSocketDisconnect) as info:
            ws.receive_json()
    assert info.value.code == call_route.CLOSE_LOCKED


def test_locked_identity_rejected_even_with_right_key():
    client = _client()
    guest = _guest_key()
    for _ in range(5):
        assert client.get("/johnny/check", headers={"X-API-Key": "nope"}).status_code == 401
    resp = client.get("/johnny/check", headers={"X-API-Key": guest})
    assert resp.status_code == 429
    assert resp.json()["detail"] == auth.LOCKED_OUT
    # still locked for a wrong key too: no hint which keys are right
    assert client.get("/johnny/check", headers={"X-API-Key": "nope"}).status_code == 429


def test_owner_key_gets_through_a_shared_lockout():
    # A guest behind the same address can't lock the owner out of his server.
    client = _client()
    for _ in range(5):
        client.get("/johnny/check", headers={"X-API-Key": "nope"})
    assert client.get("/johnny/check", headers={"X-API-Key": "secret123"}).status_code == 200
    with client.websocket_connect("/call") as ws:
        ws.send_json({"type": "hello", "key": "secret123"})
        assert ws.receive_json() == {"type": "state", "state": "speaking"}
        ws.send_json({"type": "end"})


def test_missing_key_does_not_count_toward_lockout():
    client = _client()
    for _ in range(10):
        assert client.get("/johnny/check").status_code == 401
    assert client.get("/johnny/check", headers={"X-API-Key": "secret123"}).status_code == 200


def test_http_and_ws_failures_share_one_count():
    client = _client()
    for _ in range(3):
        client.get("/johnny/check", headers={"X-API-Key": "nope"})
    _wrong_hello(client)
    _wrong_hello(client)
    assert client.get("/johnny/check", headers={"X-API-Key": _guest_key()}).status_code == 429


def test_lockout_is_audited_without_the_key(tmp_path):
    import json
    client = _client()
    for _ in range(5):
        client.get("/johnny/check", headers={"X-API-Key": "guess-xyz"})
    lines = [json.loads(l) for l in (tmp_path / "audit.log").read_text().splitlines()]
    events = [l["event"] for l in lines]
    assert events.count("auth_fail") == 5 and events.count("lockout") == 1
    assert "guess-xyz" not in (tmp_path / "audit.log").read_text()


def test_lockout_alerts_owner(monkeypatch):
    sent = []
    monkeypatch.setattr(auth.alerts, "notify",
                        lambda title, msg, dedupe: sent.append((title, dedupe)))
    client = _client()
    for _ in range(5):
        client.get("/johnny/check", headers={"X-API-Key": "nope"})
    assert [t for t, _ in sent] == ["Johnny lockout"]
    assert sent[0][1].startswith("lockout:")


# --- Page hardening (CSP) ---

def test_johnny_page_has_csp_and_headers():
    resp = _client().get("/johnny")
    csp = resp.headers["content-security-policy"]
    assert "default-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert "'unsafe-inline'" not in csp.split("script-src")[1].split(";")[0]
    assert "'unsafe-eval'" not in csp
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["referrer-policy"] == "no-referrer"
    assert resp.headers["permissions-policy"] == "microphone=(self), camera=(), geolocation=()"


def test_page_has_no_inline_script():
    import re
    html = call_route.PAGE.read_text()
    tags = re.findall(r"<script([^>]*)>", html)
    inline = [t for t in tags if "src=" not in t and 'type="importmap"' not in t]
    assert inline == []
    assert not re.search(r"\son[a-z]+\s*=", html)    # no onclick= style handlers


def _browser_importmap_text(html):
    """The import map's text as a browser's parser sees it (independent of
    the regex in call_route)."""
    from html.parser import HTMLParser

    class P(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=False)
            self.inside, self.text = False, None

        def handle_starttag(self, tag, attrs):
            self.inside = tag == "script" and dict(attrs).get("type") == "importmap"
            if self.inside:
                self.text = ""

        def handle_data(self, data):
            if self.inside:
                self.text += data

        def handle_endtag(self, tag):
            self.inside = False

    p = P()
    p.feed(html)
    return p.text


def test_importmap_is_allowed_by_exact_hash():
    import base64, hashlib
    resp = _client().get("/johnny")
    block = _browser_importmap_text(resp.text)    # the bytes actually served
    digest = base64.b64encode(hashlib.sha256(block.encode()).digest()).decode()
    assert f"'sha256-{digest}'" in resp.headers["content-security-policy"]


def test_csp_follows_page_edits_without_restart(tmp_path, monkeypatch):
    page = tmp_path / "call.html"
    page.write_text('<script type="importmap">{"imports":{}}</script>')
    monkeypatch.setattr(call_route, "PAGE", page)
    first = _client().get("/johnny").headers["content-security-policy"]
    page.write_text('<script type="importmap">{"imports":{"x":"/y"}}</script>')
    second = _client().get("/johnny").headers["content-security-policy"]
    assert first != second


def test_broken_page_fails_closed_without_taking_down_the_api(tmp_path, monkeypatch):
    page = tmp_path / "call.html"
    page.write_text("<p>no import map</p>")
    monkeypatch.setattr(call_route, "PAGE", page)
    csp = _client().get("/johnny").headers["content-security-policy"]
    assert "sha256-" not in csp and "script-src 'self' 'wasm-unsafe-eval';" in csp
    assert _client().get("/status").status_code == 200


def test_csp_names_the_call_websocket():
    csp = _client().get("/johnny", headers={"host": "johnny.example.ts.net"}).headers[
        "content-security-policy"]
    assert "wss://johnny.example.ts.net" in csp
    evil = _client().get("/johnny", headers={"host": "x; script-src *"}).headers[
        "content-security-policy"]
    assert "script-src *" not in evil


def test_only_listed_page_scripts_are_served():
    assert _client().get("/johnny/app.js").status_code == 404
    assert _client().get("/johnny/..%2Fapp.js").status_code == 404


def test_call_js_and_worklet_served():
    for path in ("/johnny/call.js", "/johnny/worklet.js"):
        resp = _client().get(path)
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/javascript")
        assert resp.headers["cache-control"] == "no-cache"
    assert "registerProcessor('mic'" in _client().get("/johnny/worklet.js").text


def test_api_responses_get_basic_headers_but_no_csp():
    for resp in (_client().get("/status"), _client().get("/johnny/check")):
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert "content-security-policy" not in resp.headers



# --- Installable app (web manifest, icons, title font) ---

def test_manifest_makes_an_installable_app():
    import json
    resp = _client().get("/johnny/manifest.webmanifest")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/manifest+json")
    m = json.loads(resp.text)
    assert m["display"] == "standalone" and m["start_url"] == "/johnny"
    sizes = {i["sizes"] for i in m["icons"]}
    assert any(i.get("purpose") == "maskable" for i in m["icons"])
    assert {"192x192", "512x512"} <= sizes
    for icon in m["icons"]:    # every icon it names is actually served
        r = _client().get(icon["src"])
        assert r.status_code == 200 and r.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_page_links_manifest_icon_and_font():
    html = _client().get("/johnny").text
    for path in ("/johnny/manifest.webmanifest", "/johnny/icons/apple-touch-icon.png",
                 "/johnny/fonts/johnny-title.woff2"):
        assert path in html
        assert _client().get(path).status_code == 200


def test_title_font_ships_with_its_license():
    assert (call_route.WEB / "fonts" / "OFL.txt").read_text().startswith("Copyright")
    assert _client().get("/johnny/fonts/johnny-title.woff2").headers["content-type"] == "font/woff2"


def test_unlisted_page_files_are_404():
    for path in ("/johnny/icons/..%2Fcall.html", "/johnny/icons/x.png", "/johnny/fonts/OFL.txt",
                 "/johnny/fonts/..%2F..%2Fapp.py", "/johnny/vendor%2F..%2F..%2Fapp.py"):
        assert _client().get(path).status_code == 404, path
    # and straight at the gate, with no URL clean-up in between
    import pytest as _pytest
    from fastapi import HTTPException as _HE
    for name in ("icons/../call.html", "../app.py", "fonts/OFL.txt"):
        with _pytest.raises(_HE):
            call_route._page_file(name)


# --- Johnny is calling: only the owner hears the event --------------------
def _rec(scope):
    from keys import KeyRecord
    return KeyRecord(id="k", scope=scope, per_minute=10, per_day_llm=10, per_day_stt_seconds=10)


def test_owner_with_valid_event_gets_an_opening():
    import events
    ev = events.add("drop", "urgent", "100k account is down 2.0% today.", key="t")
    opening = call_route._call_opening(_rec("owner"), ev["id"])
    assert "100k account is down 2.0% today." in opening


def test_guest_with_event_gets_ordinary_call():
    import events
    ev = events.add("drop", "urgent", "secret", key="t")
    assert call_route._call_opening(_rec("guest"), ev["id"]) is None


def test_unknown_or_stale_event_gets_ordinary_call():
    import events
    from datetime import datetime, timedelta, timezone
    old = events.add("drop", "urgent", "old", key="t",
                     now=datetime.now(timezone.utc) - timedelta(hours=25))
    assert call_route._call_opening(_rec("owner"), old["id"]) is None
    assert call_route._call_opening(_rec("owner"), "0123456789ab") is None


def test_bad_event_id_format_is_ignored():
    for bad in ("../events", "ABCDEF012345", "123", None, 12, {"id": 1}, "0123456789abc"):
        assert call_route._call_opening(_rec("owner"), bad) is None
