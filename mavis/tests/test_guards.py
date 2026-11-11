import os
import struct
import pytest
import guards

from guards import wav_seconds, BadAudio, MAX_UTTERANCE_SECONDS


def make_wav(
    seconds,
    rate=16000,
    channels=1,
    bits=16,
    extra_chunk=False,
    declared_size=None,
):
    """
    Build a minimal RIFF/WAVE byte sequence.
    extra_chunk adds a LIST chunk with odd size (7) to test padding handling.
    declared_size overrides the size field in the data chunk; the payload length
    is always derived from ``seconds``.
    """
    # fmt chunk (PCM)
    byte_rate = rate * channels * bits // 8
    block_align = channels * bits // 8
    fmt_payload = struct.pack("<HHIIHH", 1, channels, rate, byte_rate, block_align, bits)
    fmt_chunk = b"fmt " + struct.pack("<I", len(fmt_payload)) + fmt_payload
    if len(fmt_payload) % 2 == 1:
        fmt_chunk += b"\x00"

    # audio payload based on real seconds
    total_samples = int(seconds * rate)
    audio_bytes = total_samples * channels * bits // 8
    audio_payload = b"\x00" * audio_bytes

    # data chunk header
    data_size = declared_size if declared_size is not None else audio_bytes
    data_chunk = b"data" + struct.pack("<I", data_size) + audio_payload
    if audio_bytes % 2 == 1:  # pad follows the real payload, not the claimed size
        data_chunk += b"\x00"

    chunks = [fmt_chunk]

    if extra_chunk:
        # LIST chunk with 7 bytes payload (odd => needs padding)
        list_payload = b"ABCDEFG"
        list_chunk = b"LIST" + struct.pack("<I", len(list_payload)) + list_payload
        if len(list_payload) % 2 == 1:
            list_chunk += b"\x00"
        chunks.append(list_chunk)

    chunks.append(data_chunk)

    # RIFF header size: 4 ("WAVE") + sum of each chunk's (8 + size + pad)
    riff_payload_size = 4 + sum(len(ch) for ch in chunks)
    riff_header = b"RIFF" + struct.pack("<I", riff_payload_size) + b"WAVE"

    return riff_header + b"".join(chunks)


def test_valid_16k_mono_wav_seconds():
    wav = make_wav(1.0)
    assert wav_seconds(wav) == pytest.approx(1.0)


def test_skips_extra_chunks_with_odd_padding():
    wav = make_wav(1.0, extra_chunk=True)
    assert wav_seconds(wav) == pytest.approx(1.0)


def test_rejects_stereo():
    wav = make_wav(1.0, channels=2)
    with pytest.raises(BadAudio):
        wav_seconds(wav)


def test_rejects_44k():
    wav = make_wav(1.0, rate=44100)
    with pytest.raises(BadAudio):
        wav_seconds(wav)


def test_rejects_8bit():
    wav = make_wav(1.0, bits=8)
    with pytest.raises(BadAudio):
        wav_seconds(wav)


def test_rejects_not_riff():
    wav = make_wav(1.0)
    bad = b"FOOB" + wav[4:]  # corrupt the RIFF tag
    with pytest.raises(BadAudio):
        wav_seconds(bad)


def test_rejects_empty_bytes():
    with pytest.raises(BadAudio):
        wav_seconds(b"")


def test_rejects_no_data_chunk():
    # Build a file with only fmt chunk
    fmt_payload = struct.pack("<HHIIHH", 1, 1, 16000, 16000 * 2, 2, 16)
    fmt_chunk = b"fmt " + struct.pack("<I", len(fmt_payload)) + fmt_payload
    riff_payload_size = 4 + len(fmt_chunk)
    wav = b"RIFF" + struct.pack("<I", riff_payload_size) + b"WAVE" + fmt_chunk
    with pytest.raises(BadAudio):
        wav_seconds(wav)


def test_rejects_zero_length_audio():
    wav = make_wav(0.0)
    with pytest.raises(BadAudio):
        wav_seconds(wav)


def test_rejects_over_30s():
    wav = make_wav(31.0)
    with pytest.raises(BadAudio):
        wav_seconds(wav)


def test_custom_max_seconds():
    wav = make_wav(2.0)
    with pytest.raises(BadAudio):
        wav_seconds(wav, max_seconds=1.0)


def test_lying_header_small_only_the_measured_audio_is_kept():
    # Review Focus 1: header says 1 s, 35 s actually sent. Only the 1 s that
    # was measured goes on to speech-to-text; the hidden 34 s is dropped.
    from guards import normalize_wav
    clean, seconds = normalize_wav(make_wav(35.0, declared_size=32000))
    assert seconds == pytest.approx(1.0)
    assert len(clean) == 44 + 32000


def test_lying_header_huge_declared_size_uses_real_bytes():
    wav = make_wav(1.0, declared_size=0x7FFFFFFF)
    assert wav_seconds(wav) == pytest.approx(1.0)


def test_truncated_fmt_chunk_raises():
    # Build a fmt chunk that claims 16 bytes but cut off early
    fmt_payload = struct.pack("<HHIIHH", 1, 1, 16000, 32000, 2, 16)[:10]  # truncate
    fmt_chunk = b"fmt " + struct.pack("<I", 16) + fmt_payload
    # Pad to even length if needed
    if len(fmt_payload) % 2 == 1:
        fmt_chunk += b"\x00"
    # Minimal data chunk (1 s)
    audio = b"\x00" * 32000
    data_chunk = b"data" + struct.pack("<I", len(audio)) + audio
    riff_payload_size = 4 + len(fmt_chunk) + len(data_chunk)
    wav = b"RIFF" + struct.pack("<I", riff_payload_size) + b"WAVE" + fmt_chunk + data_chunk
    with pytest.raises(BadAudio):
        wav_seconds(wav)


def test_trailing_metadata_after_data_is_not_counted_or_sent():
    import struct
    from guards import normalize_wav
    wav = make_wav(29.5) + b"LIST" + struct.pack("<I", 20000) + b"\x00" * 20000
    clean, seconds = normalize_wav(wav)
    assert seconds == pytest.approx(29.5)
    assert len(clean) == 44 + int(29.5 * 32000)


def test_clean_wav_is_canonical_and_parses_with_wave_module():
    import io
    import wave
    from guards import normalize_wav
    clean, _ = normalize_wav(make_wav(2.0, extra_chunk=True))
    with wave.open(io.BytesIO(clean)) as w:
        assert (w.getnchannels(), w.getframerate(), w.getsampwidth()) == (1, 16000, 2)
        assert w.getnframes() == 32000


def test_data_before_fmt_is_rejected():
    import struct
    body = b"data" + struct.pack("<I", 4) + b"\x00" * 4
    with pytest.raises(BadAudio):
        wav_seconds(b"RIFF" + struct.pack("<I", 4 + len(body)) + b"WAVE" + body)


def test_odd_audio_byte_count_rounds_down_to_whole_samples():
    from guards import normalize_wav
    clean, _ = normalize_wav(make_wav(1.0) + b"\x01")
    assert (len(clean) - 44) % 2 == 0


def test_env_number_falls_back(monkeypatch):
    from guards import env_number
    for bad in ["", "lots", "nan", "-5", "inf"]:
        monkeypatch.setenv("X_TEST_NUM", bad)
        assert env_number("X_TEST_NUM", 500, minimum=1) == 500
    monkeypatch.setenv("X_TEST_NUM", "300")
    assert env_number("X_TEST_NUM", 500, minimum=1) == 300


def test_call_slots_total_and_per_key():
    from guards import CallSlots
    slots = CallSlots(max_total=2, max_per_key=1)
    assert slots.acquire("a")
    assert not slots.acquire("a")      # one call per key
    assert slots.acquire("b")
    assert not slots.acquire("c")      # two in total
    slots.release("a")
    assert slots.acquire("c")
    slots.release("b"); slots.release("c")
    slots.release("nobody")            # harmless
    assert slots.acquire("a")


# --- Failed-key lockout ---

class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_five_failures_lock_identity():
    lock = guards.Lockout(clock=_Clock())
    assert [lock.fail("ip:1.2.3.4") for _ in range(5)] == [False] * 4 + [True]
    assert lock.locked("ip:1.2.3.4")
    assert not lock.locked("ip:5.6.7.8")    # others are untouched


def test_failures_outside_the_window_do_not_add_up():
    clock = _Clock()
    lock = guards.Lockout(clock=clock)
    for _ in range(4):
        lock.fail("ip:a")
    clock.now += 601
    assert lock.fail("ip:a") is False
    assert not lock.locked("ip:a")


def test_lock_expires_after_600s():
    clock = _Clock()
    lock = guards.Lockout(clock=clock)
    for _ in range(5):
        lock.fail("ip:a")
    clock.now += 599
    assert lock.locked("ip:a")
    clock.now += 2
    assert not lock.locked("ip:a")
    assert lock.fail("ip:a") is False    # the count starts over


class _Conn:
    def __init__(self, host, headers=None):
        from types import SimpleNamespace
        self.client = SimpleNamespace(host=host) if host else None
        self.headers = headers or {}


def test_identity_prefers_tailscale_header():
    headers = {"tailscale-user-login": "me@example.com"}
    assert guards.identity(_Conn("127.0.0.1", headers)) == "ts:me@example.com"
    assert guards.identity(_Conn("127.0.0.1")) == "ip:127.0.0.1"
    assert guards.identity(_Conn(None)) == "ip:unknown"
    assert guards.identity(None) == "ip:unknown"


@pytest.mark.parametrize("host", ["::1", "::ffff:127.0.0.1", "127.0.0.2"])
def test_identity_trusts_header_from_any_loopback_form(host):
    assert guards.identity(_Conn(host, {"tailscale-user-login": "me@x"})) == "ts:me@x"


def test_identity_ignores_tailscale_header_not_from_local_proxy():
    # A direct caller could type any login to dodge the count or frame someone.
    conn = _Conn("100.64.0.9", {"tailscale-user-login": "owner@x"})
    assert guards.identity(conn) == "ip:100.64.0.9"


def test_lockout_memory_is_bounded(monkeypatch):
    lock = guards.Lockout(clock=_Clock())
    monkeypatch.setattr(guards.Lockout, "MAX_TRACKED", 10)
    for i in range(50):
        lock.fail(f"ip:{i}")
    assert len(lock._fails) <= 10


def test_locked_identities_are_pruned_too(monkeypatch):
    clock = _Clock()
    lock = guards.Lockout(clock=clock)
    monkeypatch.setattr(guards.Lockout, "MAX_TRACKED", 10)
    for i in range(30):
        for _ in range(5):
            lock.fail(f"ip:{i}")
        clock.now += 700    # each lock has expired before the next begins
    assert len(lock._fails) + len(lock._until) <= 11


def test_flood_of_new_names_does_not_reset_an_active_guesser(monkeypatch):
    clock = _Clock()
    lock = guards.Lockout(clock=clock)
    monkeypatch.setattr(guards.Lockout, "MAX_TRACKED", 10)
    lock.fail("ip:attacker")
    for i in range(9):
        lock.fail(f"ip:decoy{i}")
    for _ in range(3):
        lock.fail("ip:attacker")    # 4 failures, now newest
    for i in range(5):
        lock.fail(f"ip:flood{i}")   # forces evictions
    assert lock.fail("ip:attacker") is True
