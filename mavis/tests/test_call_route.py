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


def test_wrong_key_is_refused():
    with _client().websocket_connect("/call") as ws:
        ws.send_json({"type": "hello", "key": "nope"})
        assert ws.receive_json() == {"type": "error", "message": "wrong or missing key"}
        with pytest.raises(WebSocketDisconnect) as info:
            ws.receive_json()
    assert info.value.code == 1008


def test_missing_hello_is_refused():
    with _client().websocket_connect("/call") as ws:
        ws.send_text("not json")
        with pytest.raises(WebSocketDisconnect) as info:
            ws.receive_json()
    assert info.value.code == 1008


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
                                     "message": "MAVIS_API_KEY not set on the server"}


def test_rate_limit_is_checked_before_paid_speech_to_text(monkeypatch):
    import asyncio
    import call
    sent = []

    async def fake_stt(wav):
        sent.append(wav)
        return "hi"

    monkeypatch.setattr(call_route.avatar_stt, "transcribe_wav", fake_stt)
    monkeypatch.setattr(rate_limit, "MAX_REQUESTS_PER_WINDOW", 1)
    assert asyncio.run(call_route._call_transcribe("k", b"one")) == "hi"
    with pytest.raises(call.AnswerError):
        asyncio.run(call_route._call_transcribe("k", b"two"))
    assert sent == [b"one"]


def test_hello_does_not_use_a_rate_limit_slot():
    with _client().websocket_connect("/call") as ws:
        ws.send_json({"type": "hello", "key": "secret123"})
        ws.receive_json()
    assert not any(rate_limit._request_log.values())
