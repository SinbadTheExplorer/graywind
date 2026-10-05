"""Criterion 1 timing through the real Runtime path (no mic, no speaker).

Run from mavis/ with the backend up. The avatar may stay running: there is no
GPU worker to fight over any more.
    set -a; . ~/.mavis/env; set +a
    .venv/bin/python tools/latency_probe.py ["question" ...]
Note whether the Mac is on battery / Low Power Mode (`pmset -g | grep lowpower`).

What is timed, per question:
    endpoint  the trailing silence he waits out before he stops listening.
              Run for real: the question is spoken by `say`, padded with
              silence, and fed to capture.record_utterance block by block.
    stt       Groq Whisper on that recording.
    first     /ask/stream sent -> the first sentence's wav is on disk.
    TOTAL     end of the owner's speech -> first word OF THE ANSWER
              = endpoint + stt + first. The criterion is 3s.
              If `first` is past the runtime's filler gate, the real app
              plays a filler line before the answer can start, so that
              question is charged the gate plus the longest filler -- the
              filler is not counted as his first word.
Later sentences are checked for stalls: a sentence that is not ready when the
one before it finishes playing is a gap in the middle of his answer.
"""
import asyncio
import os
import statistics
import subprocess
import sys
import tempfile
import time

import numpy as np

sys.path.insert(0, os.getcwd())
from avatar import app as app_mod, canned, capture, stt, tts  # noqa: E402
from avatar.app import read_wav  # noqa: E402

QUESTIONS = sys.argv[1:] or [
    "What happens to gold when real yields fall?",
    "How does the Fed affect mortgage rates?",
    "Why do credit spreads widen in a panic?",
    "What does quantitative tightening do to bank reserves?",
    "What's the news in the markets today?",
]
CRITERION_SECONDS = 3.0


class Base:
    class taskMgr:
        @staticmethod
        def add(*a, **k):
            pass

    def accept(self, *a):
        pass

    def userExit(self):
        pass


class Machine:
    def note_degraded(self, reason):
        print("  DEGRADED:", reason)


def spoken_question(question, workdir):
    """The question as 16kHz audio, as the microphone would deliver it."""
    path = os.path.join(workdir, "q.wav")
    subprocess.run(["say", "-v", "Samantha", "-o", path,
                    "--data-format=LEI16@16000", question], check=True)
    samples, _rate = read_wav(path)
    return samples


def endpoint(samples):
    """(what capture kept, seconds of trailing silence it waited out)."""
    # `say` leaves its own silence at the end; cut to the last loud block so
    # the wait measured is capture's, then follow with 3s of room silence.
    usable = samples[: len(samples) // capture.BLOCK * capture.BLOCK].reshape(-1, capture.BLOCK)
    loud = np.nonzero(np.sqrt(np.mean(np.square(usable), axis=1)) >= capture.SILENCE_RMS)[0]
    speech = usable[: loud[-1] + 1].reshape(-1)
    padded = np.concatenate([speech, np.zeros(3 * capture.SAMPLE_RATE, dtype=np.float32)])
    blocks = (padded[i:i + capture.BLOCK]
              for i in range(0, len(padded) - capture.BLOCK + 1, capture.BLOCK))
    kept = capture.record_utterance(blocks=blocks)
    return kept, (len(kept) - len(speech)) / capture.SAMPLE_RATE


async def main():
    speaker = tts.Speaker()
    began = time.monotonic()
    speaker.start()
    print(f"voice {speaker.name}: warm-up {time.monotonic() - began:.1f}s "
          f"ready={speaker.ready} {speaker.last_error or ''}")
    print(f"endpoint detector: {type(capture.detector()).__name__}")
    runtime = app_mod.Runtime(Base(), object(), Machine(), speaker=speaker)
    runtime.on_render = lambda fn: fn()

    lines = canned.CannedVoice(canned.asset_dir(speaker.name)).by_moment.get("filler", [])
    longest_filler = max((len(read_wav(path)[0]) / read_wav(path)[1] for _, path in lines),
                         default=0.0)
    print(f"filler gate {app_mod.FILLER_AFTER_SECONDS:.1f}s, longest filler {longest_filler:.1f}s")

    totals, firsts, stalls_all = [], [], []
    for question in QUESTIONS:
        with tempfile.TemporaryDirectory() as workdir:
            kept, endpoint_s = endpoint(spoken_question(question, workdir))
        began = time.monotonic()
        heard = await stt.transcribe(kept, capture.SAMPLE_RATE)
        stt_s = time.monotonic() - began

        t0 = time.monotonic()
        first, stream, feeder = await runtime._answer(heard)
        ready, durations, text = [time.monotonic() - t0], [], [first[1]]
        item = first
        while item is not None:
            samples, rate = read_wav(item[0])
            durations.append(len(samples) / rate)
            item = await asyncio.to_thread(stream.next)
            if item is not None:
                ready.append(time.monotonic() - t0)
                text.append(item[1])
        await feeder
        app_mod._discard(stream)

        play, stalls = ready[0], []
        for k in range(1, len(ready)):
            end_previous = play + durations[k - 1]
            stalls.append(max(0.0, ready[k] - end_previous))
            play = max(ready[k], end_previous)
        filler = ready[0] > app_mod.FILLER_AFTER_SECONDS
        answer_first = (max(ready[0], app_mod.FILLER_AFTER_SECONDS + longest_filler)
                        if filler else ready[0])
        total = endpoint_s + stt_s + answer_first
        totals.append(total)
        firsts.append(ready[0])
        stalls_all += stalls
        print(f"{total:4.1f}s {'ok  ' if total <= CRITERION_SECONDS else 'SLOW'}"
              f"| endpoint {endpoint_s:.1f} stt {stt_s:.1f} first {ready[0]:.1f}"
              f"{' +FILLER' if filler else ''} "
              f"| {len(' '.join(text)):3d} chars, {len(ready)} sentences, "
              f"{sum(durations):.0f}s audio, gaps {[round(x, 1) for x in stalls if x > 0.05]}")
        print(f"      heard: {heard!r}\n      said:  {' '.join(text)!r}")

    print(f"\nTOTAL end of speech -> first word: median {statistics.median(totals):.1f}s "
          f"worst {max(totals):.1f}s (criterion {CRITERION_SECONDS:.0f}s)")
    print(f"first sentence after the question is sent: median "
          f"{statistics.median(firsts):.1f}s worst {max(firsts):.1f}s")
    print(f"mid-answer gaps: total {sum(stalls_all):.1f}s max {max(stalls_all, default=0):.1f}s")


asyncio.run(main())
