import textwrap

import pytest

from avatar import voice_client

FAKE_WORKER = textwrap.dedent("""
    import json, sys
    sys.stdout.write(json.dumps({"ready": True}) + "\\n")
    sys.stdout.flush()
    for line in sys.stdin:
        req = json.loads(line)
        if req.get("op") == "shutdown":
            break
        sys.stdout.write(json.dumps({"id": req.get("id"), "ok": True,
                                     "seconds": 0.1}) + "\\n")
        sys.stdout.flush()
""")

CRASHING_WORKER = 'import sys; sys.exit(1)'

SLOW_FAILING_WORKER = textwrap.dedent("""
    import json, sys
    sys.stdout.write(json.dumps({"ready": True}) + "\\n")
    sys.stdout.flush()
    for line in sys.stdin:
        req = json.loads(line)
        sys.stdout.write(json.dumps({"id": req.get("id"), "ok": False,
                                     "error": "boom"}) + "\\n")
        sys.stdout.flush()
""")

# Starts, prints nothing, never exits. The plan's readline() loop blocks here
# forever and ready_timeout never fires.
SILENT_WORKER = 'import time\nwhile True: time.sleep(0.5)\n'

# Becomes ready, then ignores every request without exiting -- a wedged model.
HANGING_WORKER = textwrap.dedent("""
    import json, sys, time
    sys.stdout.write(json.dumps({"ready": True}) + "\\n")
    sys.stdout.flush()
    for line in sys.stdin:
        time.sleep(30)
""")

# Emits the library noise real torch/chatterbox produce, on stdout, around the
# protocol messages.
NOISY_WORKER = textwrap.dedent("""
    import json, sys
    sys.stdout.write("Loading checkpoint shards:  50%|#####     |\\n")
    sys.stdout.write(json.dumps({"ready": True}) + "\\n")
    sys.stdout.flush()
    for line in sys.stdin:
        req = json.loads(line)
        if req.get("op") == "shutdown":
            break
        sys.stdout.write("FutureWarning: torch.load is deprecated\\n")
        sys.stdout.write(json.dumps({"id": req.get("id"), "ok": True}) + "\\n")
        sys.stdout.flush()
""")

FAILS_LOUDLY_WORKER = textwrap.dedent("""
    import sys
    sys.stderr.write("ModuleNotFoundError: No module named 'chatterbox'\\n")
    sys.exit(1)
""")


def _client(tmp_path, source, **kwargs):
    script = tmp_path / "worker.py"
    script.write_text(source)
    return voice_client.VoiceClient(
        python_exe="python3", worker_script=str(script),
        ref_wav=str(tmp_path / "ref.wav"), **kwargs)


def test_start_waits_for_ready(tmp_path):
    client = _client(tmp_path, FAKE_WORKER)
    try:
        client.start()
        assert client.ready is True
        assert client.degraded is False
    finally:
        client.stop()


def test_convert_returns_true_on_success(tmp_path):
    client = _client(tmp_path, FAKE_WORKER)
    try:
        client.start()
        assert client.convert("in.wav", "out.wav") is True
    finally:
        client.stop()


def test_process_is_reused_across_conversions(tmp_path):
    """The regression test for the whole design: a spawn-per-request
    implementation would show a different pid on the second call and cost
    ~16s of model load every reply."""
    client = _client(tmp_path, FAKE_WORKER)
    try:
        client.start()
        client.convert("a.wav", "b.wav")
        first_pid = client.pid
        client.convert("c.wav", "d.wav")
        assert client.pid == first_pid
    finally:
        client.stop()


def test_worker_that_fails_to_start_marks_degraded(tmp_path):
    client = _client(tmp_path, CRASHING_WORKER, ready_timeout=3.0)
    try:
        client.start()
        assert client.degraded is True
        assert client.ready is False
    finally:
        client.stop()


def test_convert_while_degraded_returns_false_instead_of_raising(tmp_path):
    client = _client(tmp_path, CRASHING_WORKER, ready_timeout=3.0)
    try:
        client.start()
        assert client.convert("in.wav", "out.wav") is False
    finally:
        client.stop()


def test_conversion_error_returns_false_and_keeps_worker_alive(tmp_path):
    client = _client(tmp_path, SLOW_FAILING_WORKER)
    try:
        client.start()
        assert client.convert("in.wav", "out.wav") is False
        assert client.pid is not None
    finally:
        client.stop()


def test_stop_is_safe_to_call_twice(tmp_path):
    client = _client(tmp_path, FAKE_WORKER)
    client.start()
    client.stop()
    client.stop()


# --- defects found reviewing the planned implementation --------------------

def test_silent_worker_times_out_instead_of_hanging_forever(tmp_path):
    """`ready_timeout` must actually fire.

    A plain `proc.stdout.readline()` blocks with no deadline, so a worker that
    starts but never prints -- a model download stalling on a dead network, say
    -- hangs the avatar at startup forever. The deadline is only checked
    between reads, so it is never reached. The crashing-worker test above does
    not catch this: that worker exits, which ends readline() immediately.
    """
    client = _client(tmp_path, SILENT_WORKER, ready_timeout=1.5, stop_timeout=0.5)
    try:
        client.start()
        assert client.ready is False
        assert client.degraded is True
        assert "in time" in client.last_error
    finally:
        client.stop()


def test_convert_times_out_on_a_wedged_worker(tmp_path):
    """CONVERT_TIMEOUT existed in the plan but was never referenced, so a
    wedged worker blocked the render loop indefinitely with no way out."""
    client = _client(tmp_path, HANGING_WORKER, ready_timeout=5.0, stop_timeout=0.5)
    try:
        client.start()
        assert client.ready is True
        assert client.convert("in.wav", "out.wav", timeout=1.0) is False
        assert client.degraded is True
    finally:
        client.stop()


def test_library_noise_on_stdout_does_not_break_the_protocol(tmp_path):
    """torch and chatterbox print progress bars and warnings. If a stray line
    is read as a response, every reply afterwards is answering the previous
    request. Non-JSON lines must be skipped, at ready and at convert."""
    client = _client(tmp_path, NOISY_WORKER)
    try:
        client.start()
        assert client.ready is True
        assert client.convert("in.wav", "out.wav") is True
    finally:
        client.stop()


def test_startup_failure_reports_the_workers_stderr(tmp_path):
    """The plan sent stderr to DEVNULL, so every startup failure looked
    identical and said nothing about the cause. This project's stated rule is
    that nothing fails silently."""
    client = _client(tmp_path, FAILS_LOUDLY_WORKER, ready_timeout=5.0)
    try:
        client.start()
        assert client.degraded is True
        assert "chatterbox" in client.last_error
    finally:
        client.stop()


def test_pid_is_none_before_start(tmp_path):
    client = _client(tmp_path, FAKE_WORKER)
    assert client.pid is None
    assert client.convert("in.wav", "out.wav") is False


def test_say_to_wav_writes_real_audio(tmp_path):
    """The scaffold ChatterboxVC re-colours. Cheap to check for real, and it
    catches a missing `say` voice, which would otherwise surface as silence."""
    path = tmp_path / "scaffold.wav"
    voice_client.say_to_wav("Wake up, samurai.", str(path))
    assert path.exists() and path.stat().st_size > 1000


# Echoes the gain it was sent, or reports the one it chose when sent none.
GAIN_WORKER = textwrap.dedent("""
    import json, sys
    sys.stdout.write(json.dumps({"ready": True}) + "\\n")
    sys.stdout.flush()
    for line in sys.stdin:
        req = json.loads(line)
        if req.get("op") == "shutdown":
            break
        sys.stdout.write(json.dumps({"id": req.get("id"), "ok": True,
                                     "gain": req.get("gain", 6.5)}) + "\\n")
        sys.stdout.flush()
""")


def test_gain_goes_to_the_worker_and_comes_back(tmp_path):
    client = _client(tmp_path, GAIN_WORKER)
    try:
        client.start()
        assert client.convert("in.wav", "out.wav")
        assert client.last_gain == 6.5          # worker normalised, said so
        assert client.convert("in.wav", "out.wav", gain=2.25)
        assert client.last_gain == 2.25         # worker used the one sent
    finally:
        client.stop()


def test_fit_cost_recovers_a_clean_line():
    pairs = [(1, 2.5), (2, 3.0), (4, 4.0), (6, 5.0)]
    assert voice_client.fit_cost(pairs) == pytest.approx((2.0, 0.5))


def test_fit_cost_shrugs_off_one_swap_storm():
    pairs = [(1, 2.5), (2, 3.0), (3, 3.5), (4, 4.0), (5, 21.0), (6, 5.0)]
    fixed, rate = voice_client.fit_cost(pairs)
    assert rate == pytest.approx(0.5) and fixed == pytest.approx(2.0)


def test_fit_cost_without_spread_is_the_cautious_default():
    assert voice_client.fit_cost([]) == voice_client.DEFAULT_COST
    assert voice_client.fit_cost([(2, 3.0), (2.2, 9.0)]) == voice_client.DEFAULT_COST


def test_fit_cost_is_clamped():
    fixed, rate = voice_client.fit_cost([(1, 100.0), (5, 0.1)])
    assert voice_client.RATE_BOUNDS[0] <= rate <= voice_client.RATE_BOUNDS[1]
    assert voice_client.FIXED_BOUNDS[0] <= fixed <= voice_client.FIXED_BOUNDS[1]


def test_the_default_cost_voices_an_answer_whole():
    """The uncalibrated planner must reproduce the pre-chunking behaviour."""
    from avatar import chunks
    text = "Gold rises when yields fall, choom. Central banks buy it. So do you."
    assert chunks.plan(text, fixed=voice_client.DEFAULT_COST[0],
                       rate=voice_client.DEFAULT_COST[1]) == [text]


CALIBRATING_WORKER = textwrap.dedent("""
    import json, sys
    sys.stdout.write(json.dumps({"ready": True,
                                 "calibration": [[1, 1.5], [4, 3.0]]}) + "\\n")
    sys.stdout.flush()
    n = 0
    for line in sys.stdin:
        req = json.loads(line)
        if req.get("op") == "shutdown":
            break
        n += 1
        sys.stdout.write(json.dumps({"id": req.get("id"), "ok": True, "gain": 1.0,
                                     "seconds": 99.0 if n == 1 else 3.5,
                                     "audio_seconds": 5.0, "cold": n == 1}) + "\\n")
        sys.stdout.flush()
""")


def test_cost_model_learns_from_calibration_and_warm_calls_only(tmp_path):
    client = _client(tmp_path, CALIBRATING_WORKER)
    try:
        client.start()
        assert client.cost_model() == pytest.approx((1.0, 0.5))
        client.convert("a.wav", "b.wav")        # cold: 99s must be ignored
        assert client.cost_model() == pytest.approx((1.0, 0.5))
        client.convert("a.wav", "b.wav")        # warm (5s -> 3.5s) fits the line
        assert client.cost_model() == pytest.approx((1.0, 0.5))
    finally:
        client.stop()
