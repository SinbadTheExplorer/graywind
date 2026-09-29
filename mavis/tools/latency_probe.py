"""Criterion 2 timing through the real Runtime._voice path (no mic, no speaker).

Run from mavis/ with the backend up and the avatar STOPPED (two voice workers
would fight over the GPU and memory):
    launchctl bootout gui/$UID/com.mavis.avatar   # or just press Escape in his window
    set -a; . ~/.mavis/env; set +a
    .venv/bin/python tools/latency_probe.py ["question" ...]
    launchctl bootstrap gui/$UID ~/Library/LaunchAgents/com.mavis.avatar.plist   # after
Note whether the Mac is on battery / Low Power Mode (`pmset -g | grep lowpower`):
on 2026-09-29 that alone made voice conversion ~3x slower.

Boundary A (the 2026-09-25 baseline's): /ask sent -> first chunk playable.
Boundary B (the owner's stopwatch):    end of speech -> first chunk playable
   = capture's 1.2s trailing-silence wait + STT + A.
Playback is simulated from each chunk's ready time and duration, so gaps
between chunks are measured, not assumed.
"""
import asyncio, os, sys, time, statistics, subprocess, tempfile
sys.path.insert(0, os.getcwd())
from avatar import app as app_mod, brain, capture, stt, voice_client
from avatar.app import read_wav

QUESTIONS = sys.argv[1:] or [
    "What happens to gold when real yields fall?",
    "How does the Fed affect mortgage rates?",
    "Why do credit spreads widen in a panic?",
    "What does quantitative tightening do to bank reserves?",
    "How does a strong dollar hit emerging markets?",
]

class Base:
    class taskMgr:
        @staticmethod
        def add(*a, **k): pass
    def accept(self, *a): pass
    def userExit(self): pass

class Machine:
    def note_degraded(self, r): print("  DEGRADED:", r)

def spoken(q, path):
    subprocess.run(["say", "-v", "Samantha", "-o", path, "--data-format=LEI16@16000", q], check=True)
    s, r = read_wav(path)
    return s

async def main():
    vc = voice_client.VoiceClient()
    t = time.monotonic(); vc.start(); print(f"warm-up {time.monotonic()-t:.1f}s ready={vc.ready} {vc.last_error or ''}")
    rt = app_mod.Runtime(Base(), object(), Machine(), voice=vc)
    rt.on_render = lambda fn: fn()
    real_say, real_conv = voice_client.say_to_wav, vc.convert
    def say_t(text, path):
        t = time.monotonic(); real_say(text, path); print(f"    say  {time.monotonic()-t:4.1f}s {len(text):3d}c {text[:60]!r}")
    def conv_t(i, o, **k):
        t = time.monotonic(); ok = real_conv(i, o, **k); print(f"    vc   {time.monotonic()-t:4.1f}s {os.path.basename(o)}"); return ok
    voice_client.say_to_wav = say_t; vc.convert = conv_t
    A, B, stalls_all = [], [], []
    for q in QUESTIONS:
        with tempfile.TemporaryDirectory() as d:
            samples = spoken(q, os.path.join(d, "q.wav"))
        t_stt = time.monotonic(); heard = await stt.transcribe(samples, 16000); stt_s = time.monotonic() - t_stt
        t0 = time.monotonic()
        answer = await brain.ask(heard)
        ask_s = time.monotonic() - t0
        print(f"    cost model F={vc.cost_model()[0]:.2f} r={vc.cost_model()[1]:.2f}")
        stream = rt._voice(answer)
        ready, durs = [], []
        while (p := await asyncio.to_thread(stream.next)) is not None:
            ready.append(time.monotonic() - t0)
            s, r = read_wav(p); durs.append(len(s) / r)
        parts = len(ready)
        app_mod._discard(stream)
        play, stalls = ready[0], []
        for k in range(1, parts):
            end_prev = play + durs[k - 1]
            play = max(ready[k], end_prev)
            stalls.append(max(0.0, ready[k] - end_prev))
        # The filler starts with /ask and must finish before the answer can.
        a = max(ready[0], FILLER_WORST); b = capture_silence + stt_s + a
        A.append(a); B.append(b); stalls_all += stalls
        print(f"{len(answer):3d} chars {parts} chunks | stt {stt_s:.1f} ask {ask_s:.1f} first-chunk-voiced {a - ask_s:.1f} "
              f"| A={a:.1f}s B={b:.1f}s | gaps {[round(x,1) for x in stalls]} | audio {sum(durs):.1f}s")
    vc.stop()
    print(f"A (baseline boundary): median {statistics.median(A):.1f}s worst {max(A):.1f}s")
    print(f"B (end of speech):     median {statistics.median(B):.1f}s worst {max(B):.1f}s")
    print(f"gaps: total {sum(stalls_all):.1f}s max {max(stalls_all, default=0):.1f}s")

capture_silence = 1.2
FILLER_WORST = 4.51   # longest canned filler line, seconds
asyncio.run(main())
