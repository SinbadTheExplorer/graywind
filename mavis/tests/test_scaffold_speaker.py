"""The warm Tom helper behind `say_to_wav`, and its fallback to `say`."""
import os
import stat
import textwrap

import numpy as np
import pytest
from scipy.io import wavfile

from avatar import voice_client


def _fake_helper(tmp_path, body):
    """A stand-in 'binary' that already exists, so no build is attempted."""
    source = tmp_path / "speaker.swift"
    source.write_text("// unused")
    binary = tmp_path / "speaker"
    binary.write_text("#!/usr/bin/env python3\nimport json, sys\n" + textwrap.dedent(body))
    binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
    return voice_client.ScaffoldSpeaker(source=str(source), binary=str(binary),
                                        render_timeout=2)


READY = 'print(json.dumps({"ready": True}), flush=True)\n'


def test_real_helper_writes_the_same_samples_as_say(tmp_path):
    speaker = voice_client.ScaffoldSpeaker(binary=str(tmp_path / "bin" / "speaker"))
    try:
        assert speaker.start(), speaker.last_error
        text = "Gold climbs when real yields fall, choom."
        assert speaker.render(text, str(tmp_path / "fast.wav"))
    finally:
        speaker.stop()
    voice_client.subprocess.run(["say", "-v", "Tom", "-o", str(tmp_path / "say.wav"),
                                 "--data-format=LEF32@22050", text], check=True)
    fast_rate, fast = wavfile.read(tmp_path / "fast.wav")
    say_rate, said = wavfile.read(tmp_path / "say.wav")
    assert fast_rate == say_rate == 22050 and fast.dtype == np.float32
    assert np.array_equal(fast, said)


def test_missing_voice_refuses_to_start(tmp_path):
    speaker = voice_client.ScaffoldSpeaker(binary=str(tmp_path / "speaker"),
                                           voice="com.apple.voice.not-a-voice")
    assert speaker.start() is False
    assert "voice not installed" in speaker.last_error


def test_a_speaker_that_never_answers_is_turned_off(tmp_path):
    speaker = _fake_helper(tmp_path, READY + "for line in sys.stdin: pass\n")
    assert speaker.start()
    assert speaker.render("hello", str(tmp_path / "x.wav")) is False
    assert speaker.ready is False and speaker.last_error == "no reply"


def test_a_reply_out_of_step_is_turned_off(tmp_path):
    speaker = _fake_helper(tmp_path, READY + textwrap.dedent("""
        for line in sys.stdin:
            print(json.dumps({"id": 99, "ok": True}), flush=True)
    """))
    assert speaker.start()
    assert speaker.render("hello", str(tmp_path / "x.wav")) is False
    assert speaker.ready is False


def test_one_failed_utterance_keeps_the_speaker(tmp_path):
    speaker = _fake_helper(tmp_path, READY + textwrap.dedent("""
        for line in sys.stdin:
            print(json.dumps({"id": json.loads(line)["id"], "ok": False,
                              "error": "nope"}), flush=True)
    """))
    assert speaker.start()
    assert speaker.render("hello", str(tmp_path / "x.wav")) is False
    assert speaker.ready is True
    speaker.stop()


def test_say_to_wav_falls_back_to_say_when_the_speaker_fails(tmp_path, monkeypatch):
    speaker = _fake_helper(tmp_path, READY + "for line in sys.stdin: pass\n")
    assert speaker.start()
    monkeypatch.setattr(voice_client, "_speaker", speaker)
    path = tmp_path / "scaffold.wav"
    voice_client.say_to_wav("Wake up, samurai.", str(path))
    assert path.stat().st_size > 1000 and speaker.ready is False


@pytest.mark.parametrize("body", ["sys.exit(3)\n",
                                  'print(json.dumps({"ready": False, "error": "x"}))\n'])
def test_a_helper_that_fails_at_startup_is_off(tmp_path, body):
    speaker = _fake_helper(tmp_path, body)
    assert speaker.start() is False
    assert speaker.render("hello", str(tmp_path / "x.wav")) is False


def test_stop_before_start_finishes_means_no_helper(tmp_path):
    """Escape during the first build: the start thread must not launch it after."""
    speaker = _fake_helper(tmp_path, READY + "for line in sys.stdin: pass\n")
    speaker.stop()
    assert speaker.start() is False
    assert speaker.proc is None and speaker.ready is False


def test_a_failed_warm_up_is_reported_not_ready(tmp_path):
    speaker = _fake_helper(tmp_path, 'print(json.dumps({"ready": False, '
                                     '"error": "warm-up failed: x"}))\n')
    assert speaker.start() is False
    assert "warm-up failed" in speaker.last_error


def test_the_binary_is_named_by_its_source(tmp_path, monkeypatch):
    """Worktrees share ~/.mavis/bin; each source must get its own binary."""
    monkeypatch.setattr(voice_client, "SPEAKER_BIN_DIR", str(tmp_path / "bin"))
    names = []
    for text in ("// one", "// two"):
        source = tmp_path / f"{len(names)}.swift"
        source.write_text(text)
        speaker = voice_client.ScaffoldSpeaker(source=str(source))
        monkeypatch.setattr(voice_client.subprocess, "run",
                            lambda cmd, **k: open(cmd[-1], "w").close())
        speaker._build()
        names.append(os.path.basename(speaker.binary))
    assert names[0] != names[1] and all(n.startswith("scaffold_speaker-") for n in names)
