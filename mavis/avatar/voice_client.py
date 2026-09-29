"""Owns the warm ChatterboxVC worker subprocess.

Every failure here degrades to plain `say` rather than silence, and sets
`degraded` so the UI can show it. A voice assistant that goes quiet with no
explanation is the failure mode this project explicitly rejects.

The worker's output is drained by a background thread into a queue rather than
read with `proc.stdout.readline()`. That is not incidental: a bare readline()
blocks with no deadline, so both timeouts here would be decorative -- a worker
that starts but never speaks would hang the avatar at startup forever, and a
wedged model would block the render loop with no way out. Reading through a
queue is what makes `ready_timeout` and `CONVERT_TIMEOUT` real.

Non-JSON lines are skipped everywhere. torch and chatterbox print progress bars
and warnings, and a stray line read as a response would leave every later reply
answering the previous request. The worker also redirects library output away
from stdout; this is the second half of that defence.
"""
import collections
import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path

NARRATION_PYTHON = os.environ.get(
    "MAVIS_VOICE_PYTHON",
    str(Path.home() / "minhthanh0403/claude-projects/claudekit/bullion-live-map"
        "/.venv-narration/bin/python"),
)
ACTOR_REF_WAV = os.environ.get(
    "MAVIS_ACTOR_REF",
    str(Path.home() / "minhthanh0403/claude-projects/claudekit/bullion-live-map"
        "/audio/voice_sample/actor_sample.wav"),
)
WORKER_SCRIPT = str(Path(__file__).resolve().parent.parent / "scripts" / "voice_worker.py")

# Model load plus compiling the first-chunk buckets. Load alone hit 59s under
# heavy swap on 2026-09-28, and missing this deadline degrades the whole
# session to the plain voice, so it is generous.
READY_TIMEOUT = 240.0
CONVERT_TIMEOUT = 120.0
# How long a shutdown request is given before the worker is killed. A healthy
# worker answers at once; this only costs time when one is already wedged.
STOP_TIMEOUT = 5.0

# ChatterboxVC emits at this rate regardless of the reference clip's rate, and
# it is what Task 7 must hand to lipsync.envelope(). Passing the reference's
# 22050 instead would stretch the envelope against the audio and drift the
# mouth out of sync over a long answer.
OUTPUT_SAMPLE_RATE = 24000

_EOF = object()

# Before any timing is known: slower than realtime, so the chunk planner puts
# most of the answer in the first chunk and plans no gap. Never optimistic.
DEFAULT_COST = (2.5, 1.2)
# Clamp a fitted model to what this hardware can physically do, so one swap
# storm cannot talk the planner into nonsense.
FIXED_BOUNDS = (0.2, 10.0)
RATE_BOUNDS = (0.1, 3.0)
TIMING_WINDOW = 12


def fit_cost(pairs, default=DEFAULT_COST):
    """(fixed, rate) with conversion = fixed + rate * padded (bucket) seconds.

    Theil-Sen: the median of pairwise slopes, then the median intercept.
    Medians rather than least squares because single calls here have jumped
    from 6s to 21s under swap, and one of those would drag a mean fit off.
    """
    slopes = [(t2 - t1) / (d2 - d1)
              for i, (d1, t1) in enumerate(pairs)
              for d2, t2 in pairs[i + 1:] if abs(d2 - d1) >= 0.5]
    if not slopes:
        return default
    rate = min(max(_median(slopes), RATE_BOUNDS[0]), RATE_BOUNDS[1])
    fixed = _median([t - rate * d for d, t in pairs])
    return min(max(fixed, FIXED_BOUNDS[0]), FIXED_BOUNDS[1]), rate


def _median(values):
    values = sorted(values)
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2


def say_to_wav(text: str, path: str) -> None:
    """macOS `say` scaffold that ChatterboxVC re-colours into Johnny."""
    subprocess.run(
        ["say", "-v", "Tom", "-o", path, "--data-format=LEF32@22050", text],
        check=True,
    )


class VoiceClient:
    def __init__(self, python_exe=NARRATION_PYTHON, worker_script=WORKER_SCRIPT,
                 ref_wav=ACTOR_REF_WAV, ready_timeout=READY_TIMEOUT,
                 stop_timeout=STOP_TIMEOUT):
        self.python_exe = python_exe
        self.worker_script = worker_script
        self.ref_wav = ref_wav
        self.ready_timeout = ready_timeout
        self.stop_timeout = stop_timeout
        self.proc = None
        self.ready = False
        self.degraded = False
        self.last_error = None
        self.device = None
        self.last_gain = None
        self._timings = collections.deque(maxlen=TIMING_WINDOW)
        self._next_id = 0
        self._lock = threading.Lock()
        self._messages = queue.Queue()
        self._stderr = collections.deque(maxlen=40)

    @property
    def pid(self):
        return self.proc.pid if self.proc and self.proc.poll() is None else None

    def _drain_stdout(self, stream):
        for line in stream:
            self._messages.put(line)
        self._messages.put(_EOF)

    def _drain_stderr(self, stream):
        for line in stream:
            self._stderr.append(line.rstrip())

    def _stderr_tail(self, limit=3):
        lines = [line for line in self._stderr if line.strip()]
        return " | ".join(lines[-limit:])

    def _next_message(self, deadline):
        """Next JSON object from the worker, or None on timeout or exit.

        Skips anything that is not JSON so library chatter cannot be mistaken
        for a protocol message.
        """
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            try:
                line = self._messages.get(timeout=remaining)
            except queue.Empty:
                return None
            if line is _EOF:
                return None
            try:
                return json.loads(line)
            except ValueError:
                continue

    def start(self) -> None:
        try:
            self.proc = subprocess.Popen(
                [self.python_exe, self.worker_script, self.ref_wav],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, bufsize=1,
            )
        except OSError as exc:
            self._degrade(f"could not launch voice worker: {exc}")
            return

        for target, stream in ((self._drain_stdout, self.proc.stdout),
                               (self._drain_stderr, self.proc.stderr)):
            thread = threading.Thread(target=target, args=(stream,), daemon=True)
            thread.start()

        deadline = time.monotonic() + self.ready_timeout
        while True:
            message = self._next_message(deadline)
            if message is None:
                detail = self._stderr_tail()
                if self.proc.poll() is not None:
                    reason = "voice worker exited before becoming ready"
                elif time.monotonic() >= deadline:
                    reason = "voice worker did not become ready in time"
                else:
                    reason = "voice worker closed its output before ready"
                self._degrade(f"{reason}{': ' + detail if detail else ''}")
                return
            if message.get("ready"):
                self.ready = True
                self.device = message.get("device")
                for pair in message.get("calibration") or ():
                    self._timings.append(tuple(pair))
                return
            if "ready" in message:
                detail = message.get("error") or self._stderr_tail()
                self._degrade(f"voice worker failed to load: {detail}")
                return

    def convert(self, in_path: str, out_path: str, timeout=CONVERT_TIMEOUT,
                gain=None) -> bool:
        """True if `out_path` now holds Johnny-voiced audio.

        `gain` fixes the output level instead of normalising the clip, so the
        chunks of one answer share a loudness; `last_gain` is the gain the
        worker used, to pass to the next chunk.
        """
        if not self.ready or self.pid is None:
            return False

        with self._lock:
            self._next_id += 1
            request = {"id": self._next_id, "op": "convert",
                       "input": in_path, "output": out_path}
            if gain is not None:
                request["gain"] = gain
            try:
                self.proc.stdin.write(json.dumps(request) + "\n")
                self.proc.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                self._degrade(f"voice worker pipe broke: {exc}")
                return False

            message = self._next_message(time.monotonic() + timeout)

        if message is None:
            if self.proc.poll() is not None:
                self._degrade("voice worker died mid-conversion")
            else:
                # Still running but unresponsive: the reply for this request may
                # yet arrive and would be read as the answer to the next one, so
                # the worker cannot be trusted again.
                self._degrade(f"voice worker did not answer within {timeout:.0f}s")
            return False

        if not message.get("ok"):
            self.last_error = message.get("error", "voice conversion failed")
            return False
        self.last_gain = message.get("gain")
        # A call that compiled a new bucket measures the compile, not the
        # machine, and would make the planner needlessly pessimistic.
        # Keyed on the padded length, which is what the call actually cost.
        if "bucket_seconds" in message and not message.get("cold"):
            self._timings.append((message["bucket_seconds"], message["seconds"]))
        return True

    def cost_model(self):
        """(fixed, rate) from this session's recent warm conversions."""
        return fit_cost(list(self._timings))

    def _degrade(self, reason: str) -> None:
        self.ready = False
        self.degraded = True
        self.last_error = reason

    def stop(self) -> None:
        if self.proc is None:
            return
        try:
            if self.proc.poll() is None:
                self.proc.stdin.write(json.dumps({"op": "shutdown"}) + "\n")
                self.proc.stdin.flush()
                self.proc.wait(timeout=self.stop_timeout)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            self.proc.kill()
            try:
                self.proc.wait(timeout=self.stop_timeout)
            except subprocess.TimeoutExpired:
                pass
        finally:
            self.proc = None
            self.ready = False
