import os
import threading

import pytest

from avatar.voice_stream import VoiceStream


class Fake:
    def __init__(self, fail_at=None, gain=2.5, scaffold_error_at=None):
        self.fail_at = fail_at
        self.gain = gain
        self.scaffold_error_at = scaffold_error_at
        self.scaffolded, self.converted, self.gains = [], [], []
        self.degraded = 0

    def scaffold(self, text, path):
        if text == self.scaffold_error_at:
            raise OSError("say failed")
        self.scaffolded.append(text)

    def convert(self, src, out, gain):
        index = int(src.rsplit("-", 1)[1].split(".")[0])
        self.converted.append(index)
        self.gains.append(gain)
        if index == self.fail_at:
            return False, None
        return True, gain or self.gain

    def on_degraded(self):
        self.degraded += 1


def _drain(stream):
    out = []
    while (path := stream.next(timeout=5)) is not None:
        out.append(os.path.basename(path))
    return out


def _stream(fake, chunks):
    return VoiceStream(chunks, "/w", scaffold=fake.scaffold, convert=fake.convert,
                       on_degraded=fake.on_degraded).start()


def test_chunks_come_out_converted_and_in_order():
    fake = Fake()
    assert _drain(_stream(fake, ["a", "b", "c"])) == [
        "voice-0.wav", "voice-1.wav", "voice-2.wav"]
    assert sorted(fake.scaffolded) == ["a", "b", "c"]


def test_every_chunk_reuses_the_first_chunks_gain():
    fake = Fake(gain=3.0)
    _drain(_stream(fake, ["a", "b", "c"]))
    assert fake.gains == [None, 3.0, 3.0]


def test_a_failed_conversion_plays_the_scaffold_and_is_not_retried():
    fake = Fake(fail_at=1)
    assert _drain(_stream(fake, ["a", "b", "c", "d"])) == [
        "voice-0.wav", "scaffold-1.wav", "scaffold-2.wav", "scaffold-3.wav"]
    assert fake.converted == [0, 1]
    assert fake.degraded == 1


def test_a_producer_error_reaches_the_consumer():
    fake = Fake(scaffold_error_at="b")
    stream = _stream(fake, ["a", "b"])
    assert stream.next(timeout=5).endswith("voice-0.wav")
    with pytest.raises(OSError):
        stream.next(timeout=5)
    assert stream.next(timeout=5) is None


def test_a_success_without_a_gain_is_still_a_success():
    fake = Fake(gain=None)
    assert _drain(_stream(fake, ["a", "b"])) == ["voice-0.wav", "voice-1.wav"]
    assert fake.degraded == 0


def test_empty_answer_ends_at_once():
    assert _drain(_stream(Fake(), [])) == []


def test_cancel_wakes_a_waiting_consumer_and_stops_converting():
    gate = threading.Event()
    fake = Fake()
    slow = fake.convert

    def blocking_convert(src, out, gain):
        gate.wait(5)
        return slow(src, out, gain)

    stream = VoiceStream(["a", "b", "c"], "/w", scaffold=fake.scaffold,
                         convert=blocking_convert).start()
    stream.cancel()
    assert stream.next(timeout=5) is None
    gate.set()
    threading.Event().wait(0.2)
    assert len(fake.converted) <= 1
