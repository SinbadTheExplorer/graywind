"""Voice an answer chunk by chunk, so he can start before the rest is ready.

A producer thread converts chunk 0 first -- it alone sets time-to-first-word
-- while the plain `say` scaffolds for the later chunks are written ahead on a
second thread, so neither step waits on the other. The consumer (`Runtime._speak`)
pulls finished wavs in order with `next()`.

Loudness: chunk 0 is normalised and reports the gain it needed; every later
chunk is sent that gain instead of being normalised on its own. In practice
(2026-09-28) chunk 0 is short and quiet, so its gain is high and later chunks
mostly land on the worker's 0.99 clip guard -- close to per-chunk peak
normalisation, a peak ~1dB above chunk 0's. Not a loudness match, but no
chunk can come out quieter than chunk 0 or clip.

Failure: a chunk whose conversion fails plays as its plain scaffold instead of
silence, and conversion is not tried again for the rest of the answer -- a
worker that just failed cannot be trusted with the next request (see
`voice_client.convert`). The shape of the first draft came from `delegate`.
"""
import concurrent.futures
import os
import queue
import threading

_END = None


class VoiceStream:
    def __init__(self, chunks, workdir, *, scaffold, convert, on_degraded=None):
        """`convert(in, out, gain)` returns (ok, gain_to_reuse).

        A tuple rather than "gain or None": converting near-silence succeeds
        without producing a gain, and must not read as a failure.
        """
        self._chunks = list(chunks)
        self.workdir = workdir
        self._scaffold = scaffold
        self._convert = convert
        self._on_degraded = on_degraded
        self._queue = queue.Queue()
        self._cancelled = threading.Event()
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self._done = False

    def _path(self, kind, i):
        return os.path.join(self.workdir, f"{kind}-{i}.wav")

    def start(self):
        threading.Thread(target=self._run, name="mavis-voice-stream",
                         daemon=True).start()
        return self

    def next(self, timeout=None):
        """The next wav to play, None when the answer is finished.

        Re-raises whatever stopped the producer. `queue.Empty` on timeout.
        """
        if self._done:
            return None
        item = self._queue.get(timeout=timeout)
        if item is _END or isinstance(item, BaseException):
            self._done = True
        if isinstance(item, BaseException):
            raise item
        return item

    def cancel(self):
        self._cancelled.set()
        self._executor.shutdown(wait=False, cancel_futures=True)
        self._queue.put(_END)       # wake a consumer blocked in next()

    def _run(self):
        try:
            self._produce()
        except BaseException as exc:    # handed to the consumer, not lost here
            self._queue.put(exc)
        else:
            self._queue.put(_END)
        finally:
            self._executor.shutdown(wait=False, cancel_futures=True)

    def _produce(self):
        if not self._chunks or self._cancelled.is_set():
            return
        self._scaffold(self._chunks[0], self._path("scaffold", 0))
        ahead = {}
        for i in range(1, len(self._chunks)):
            ahead[i] = self._executor.submit(
                self._scaffold, self._chunks[i], self._path("scaffold", i))

        gain, converting = None, True
        for i in range(len(self._chunks)):
            if self._cancelled.is_set():
                return
            if i:
                ahead[i].result()
            scaffold = self._path("scaffold", i)
            if converting:
                ok, applied = self._convert(scaffold, self._path("voice", i), gain)
                if self._cancelled.is_set():
                    # Its files may already be deleted; a failure now is ours,
                    # not the voice's, and must not put a notice on screen.
                    return
                if ok:
                    gain = applied if gain is None else gain
                    self._queue.put(self._path("voice", i))
                    continue
                converting = False
                if self._on_degraded is not None:
                    self._on_degraded()
            self._queue.put(scaffold)
