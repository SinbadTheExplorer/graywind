"""The avatar's runtime: mic, speech, backend and voice around `states`.

Two threads, one rule. Panda3D owns the main thread and must keep drawing,
so the conversation -- wake word, recording, STT, /ask, voice conversion and
audio playback, all of which block -- runs on one worker thread. The worker
never touches the scene or the state machine directly; it hands callables to
the render thread through `on_render` and waits for their result. Moving a
joint off the render thread races `forceUpdate` inside the frame and fails
intermittently rather than loudly.

Run from `mavis/`:  .venv/bin/python -m avatar.app
Press W to wake him without the wake word (the trained model may not exist
yet); Escape quits.
"""
import asyncio
import os
import queue
import shutil
import sys
import tempfile
import threading
import time

import numpy as np
from scipy.io import wavfile

from avatar import (brain, capture, chunks, dismiss, lipsync, states, stt,
                    voice_client)
from avatar.voice_stream import VoiceStream

# Idle prompts he gives into silence before he gives up and goes dark.
SILENCE_PROMPTS = 2


def read_wav(path: str):
    """Mono float32 samples and the file's own rate.

    stdlib `wave` refuses both audio paths here: the VC worker writes float32
    (format 3), and so does the `say` scaffold. The rate is read rather than
    assumed -- converted and canned audio are 24000Hz, the scaffold 22050, and
    feeding lipsync the wrong one drifts the mouth off the words.
    """
    rate, data = wavfile.read(path)
    if data.dtype.kind in "iu":
        data = data.astype(np.float32) / float(np.iinfo(data.dtype).max)
    if data.ndim > 1:
        data = data.mean(axis=1)
    return data.astype(np.float32), rate


def has_speech(samples: np.ndarray) -> bool:
    """True if any capture block rose above the silence floor.

    Whisper transcribes pure room noise as "Thank you." often enough that
    silence must never reach STT, or a quiet room reads as a dismissal.
    """
    usable = samples[: len(samples) // capture.BLOCK * capture.BLOCK]
    if usable.size == 0:
        return False
    blocks = usable.reshape(-1, capture.BLOCK)
    return bool((np.sqrt(np.mean(np.square(blocks), axis=1)) >= capture.SILENCE_RMS).any())


def _measure(text: str, workdir: str):
    """(seconds, scaffold) for planning and voicing `text`.

    With the warm Tom helper up, every piece the planner can cut at is spoken
    once (~0.2s for a whole answer) and the plan runs on real durations; a
    chunk that is exactly one of those pieces -- usually chunk 0 -- reuses its
    file instead of being spoken again. Without the helper that would be
    ~1.2s of `say` per piece, so the character estimate is used instead.
    """
    if not voice_client.speaker_ready():
        return chunks.spoken_seconds, voice_client.say_to_wav
    measured, durations = {}, []
    pieces = chunks.pieces(text)
    try:
        for i, piece in enumerate(pieces):
            if not voice_client.speaker_ready():
                # Died mid-answer: the rest would be measured at `say` speed.
                return chunks.spoken_seconds, voice_client.say_to_wav
            path = os.path.join(workdir, f"piece-{i}.wav")
            voice_client.say_to_wav(piece, path)
            samples, rate = read_wav(path)
            durations.append(len(samples) / rate)
            measured.setdefault(piece, path)
    except Exception:  # noqa: BLE001 - planning on estimates beats not answering
        return chunks.spoken_seconds, voice_client.say_to_wav

    def scaffold(chunk, path):
        if chunk in measured:
            shutil.copyfile(measured[chunk], path)
        else:
            voice_client.say_to_wav(chunk, path)
    return chunks.measured_seconds(pieces, durations), scaffold


def _discard(stream) -> None:
    """Stop producing an answer's audio and delete its files. Cannot raise."""
    stream.cancel()
    shutil.rmtree(stream.workdir, ignore_errors=True)


class Runtime:
    def __init__(self, base, scene, machine, voice=None, listener=None):
        self.base = base
        self.scene = scene
        self.machine = machine
        self.voice = voice
        self.listener = listener
        self._inbox = queue.Queue()
        self._manual_wake = threading.Event()
        self._stopping = threading.Event()
        self._mouth = None          # (envelope, brows, start) while audio plays
        self._mouth_open = False
        self._answer_fault = None   # a chunk of the current answer lost its voice
        base.taskMgr.add(self._tick, "mavis-runtime")
        base.accept("w", self._manual_wake.set)
        base.accept("escape", base.userExit)

    # -- render thread ------------------------------------------------------

    def _tick(self, task):
        while True:
            try:
                job = self._inbox.get_nowait()
            except queue.Empty:
                break
            job()
        # A model without clips synthesises its idle motion here; one with
        # clips returns immediately and Panda3D advances the animation itself.
        # Nothing else calls this, so leaving it out froze such a model solid.
        self.scene.idle(task.time)
        mouth = self._mouth
        if mouth is not None:
            env, brows, start = mouth
            elapsed = time.monotonic() - start
            self.scene.set_mouth(lipsync.amount_at(env, elapsed))
            self.scene.set_brows(lipsync.amount_at(brows, elapsed))
            self._mouth_open = True
        elif self._mouth_open:
            self.scene.set_mouth(0.0)
            self.scene.set_brows(0.0)
            self._mouth_open = False
        return task.cont

    def on_render(self, fn):
        """Run `fn` on the render thread; block this worker for its result."""
        done, box = threading.Event(), {}

        def job():
            try:
                box["value"] = fn()
            except BaseException as exc:    # re-raised on the worker
                box["error"] = exc
            done.set()

        self._inbox.put(job)
        # Once the render loop has exited nothing will ever run the job, and a
        # worker parked here would hold the interpreter open at exit.
        while not done.wait(0.1):
            if self._stopping.is_set():
                raise RuntimeError("avatar is shutting down")
        if "error" in box:
            raise box["error"]
        return box.get("value")

    # -- worker thread ------------------------------------------------------

    def say(self, path) -> None:
        """Play a wav to the end with the mouth following it. None is silence."""
        if not path:
            return
        import sounddevice as sd
        samples, rate = read_wav(path)
        env = lipsync.envelope(samples, rate)
        sd.play(samples, rate)
        self._mouth = (env, lipsync.emphasis(env), time.monotonic())
        try:
            sd.wait()
        finally:
            self._mouth = None

    def stop(self) -> None:
        """Release the worker so the interpreter can exit.

        asyncio.to_thread runs on executor threads that are joined at exit, so
        one parked waiting for a wake word would hang Escape forever.
        """
        self._stopping.set()
        self._manual_wake.set()

    def wait_for_wake(self) -> None:
        self._manual_wake.clear()    # a W pressed mid-conversation is stale
        if self.listener is None:
            self._manual_wake.wait()
            self._manual_wake.clear()
            return
        import sounddevice as sd
        from avatar import wake
        with sd.InputStream(samplerate=wake.SAMPLE_RATE, channels=1,
                            dtype="int16", blocksize=wake.FRAME_SAMPLES) as stream:
            while not self._manual_wake.is_set():
                frame, _overflowed = stream.read(wake.FRAME_SAMPLES)
                if self.listener.detect(frame[:, 0]):
                    return
        self._manual_wake.clear()

    def _voice(self, text: str) -> VoiceStream:
        """Johnny-voiced chunks of `text`, produced while earlier ones play.

        A chunk whose conversion fails plays as its plain scaffold, and the
        failure goes on screen, exactly as a whole failed answer used to.
        """
        workdir = tempfile.mkdtemp(prefix="mavis-")
        fixed, rate = (self.voice.cost_model() if self.voice is not None
                       else voice_client.DEFAULT_COST)
        seconds, scaffold = _measure(text, workdir)
        parts = chunks.plan(text, fixed=fixed, rate=rate, seconds=seconds)

        def convert(src, out, gain):
            if self.voice is None or not self.voice.convert(src, out, gain=gain):
                return False, None
            return True, self.voice.last_gain

        self._answer_fault = None

        def degraded():
            reason = self.voice.last_error
            # Remembered as well as shown: `_settle_notice` runs right after
            # the first chunk is ready and would otherwise wipe this at once.
            self._answer_fault = reason
            if reason:
                try:
                    self.on_render(lambda: self.machine.note_degraded(reason))
                except RuntimeError:
                    pass    # shutting down; nothing left to show it on

        stream = VoiceStream(parts, workdir, scaffold=scaffold,
                             convert=convert,
                             on_degraded=degraded if self.voice else None)
        return stream.start()

    def _speak(self, first: str, stream: VoiceStream) -> None:
        """Play the answer's chunks back to back as they become ready."""
        path = first
        while path is not None:
            self.say(path)
            path = stream.next()

    def _settle_notice(self) -> None:
        """Clear a stale error, but keep saying so while the voice is degraded.

        Render thread. A notice left up after the fault has passed claims
        something is broken that is not -- as misleading as no notice at all.
        """
        if self.voice is not None and self.voice.degraded:
            self.machine.note_degraded(self.voice.last_error or "worker unavailable")
        elif self._answer_fault:
            self.machine.note_degraded(self._answer_fault)
        else:
            self.scene.show_notice("")

    async def _answer(self, question: str):
        """(first wav, the stream of the rest, the exact answer text).

        Returns once the FIRST chunk is voiced, not the whole answer -- that
        is the point of chunking. The text is returned rather than re-derived
        so the caption is the answer itself, not a transcription of his audio.
        """
        answer = await brain.ask(question)
        if not answer:
            raise brain.BrainError("the backend returned an empty answer")
        # Off the event loop: measuring the answer runs the speech helper.
        stream = await asyncio.to_thread(self._voice, answer)
        try:
            first = await asyncio.to_thread(stream.next)
        except BaseException:
            _discard(stream)
            raise
        if first is None:
            _discard(stream)
            raise brain.BrainError("the answer produced no audio")
        return first, stream, answer

    async def _conversation(self) -> None:
        """One wake-to-dismissal session."""
        greeting = self.on_render(
            lambda: (self._settle_notice(), self.machine.on_wake())[1])
        await asyncio.to_thread(self.say, greeting and greeting[1])

        silent = 0
        while True:
            samples = await asyncio.to_thread(capture.record_utterance)
            if not has_speech(samples):
                silent += 1
                if silent > SILENCE_PROMPTS:
                    text = dismiss.PHRASES[0]   # gone quiet: leave as if told to
                else:
                    line = self.on_render(self.machine.on_silence)
                    await asyncio.to_thread(self.say, line and line[1])
                    continue
            else:
                silent = 0
                try:
                    text = await stt.transcribe(samples, capture.SAMPLE_RATE)
                except stt.STTError as exc:
                    self.on_render(lambda: self.scene.show_notice(str(exc)))
                    continue

            kind, line = self.on_render(lambda: self.machine.on_transcript(text))
            if kind == "ignore":
                continue
            if kind == "dismiss":
                await asyncio.to_thread(self.say, line and line[1])
                self.on_render(self.machine.sleep)
                return

            # The filler covers the wait: it plays while the answer is fetched
            # and converted, rather than after.
            pending = asyncio.create_task(self._answer(text))
            try:
                await asyncio.to_thread(self.say, line and line[1])
            except BaseException:
                pending.cancel()
                raise
            try:
                first, stream, answer_text = await pending
            except brain.BrainError as exc:
                self.on_render(lambda: self.machine.on_failure(str(exc)))
                continue
            try:
                self.on_render(lambda: (self._settle_notice(),
                                        self.scene.show_caption(answer_text),
                                        self.machine.on_answer_ready()))
                await asyncio.to_thread(self._speak, first, stream)
            finally:
                # Discard FIRST: it cannot raise, and on_render can. Escape
                # pressed mid-sentence sets _stopping, the render loop is
                # already gone, and on_render gives up with RuntimeError --
                # which would otherwise skip this cleanup and replace whatever
                # `say` was propagating with a shutdown error.
                _discard(stream)
                self._answer_fault = None   # shown for this answer only
                try:
                    self.on_render(lambda: self.scene.show_caption(""))
                except RuntimeError:
                    pass    # shutting down; there is no screen left to clear
            self.on_render(self.machine.on_spoken)

    async def _serve(self) -> None:
        if self.voice is not None:
            self.on_render(lambda: self.scene.show_notice("Warming up his voice..."))
            await asyncio.to_thread(self.voice.start)
            if self.voice.degraded:
                reason = self.voice.last_error or "worker unavailable"
                self.on_render(lambda: self.machine.note_degraded(reason))
            else:
                self.on_render(lambda: self.scene.show_notice(""))
        while not self._stopping.is_set():
            try:
                await asyncio.to_thread(self.wait_for_wake)
                if self._stopping.is_set():
                    return
                await self._conversation()
            except Exception as exc:
                # A dead worker thread leaves a window that looks alive and
                # never answers again. Say what broke, go back to sleep, and
                # keep listening.
                message = f"{type(exc).__name__}: {exc}"
                print(f"conversation failed: {message}", file=sys.stderr)
                self._mouth = None
                self.on_render(lambda: (self.machine.sleep(),
                                        self.scene.show_notice(message)))
                await asyncio.sleep(1.0)

    def start(self) -> threading.Thread:
        worker = threading.Thread(target=asyncio.run, args=(self._serve(),),
                                  name="mavis-conversation", daemon=True)
        worker.start()
        return worker


def main() -> int:
    from panda3d.core import loadPrcFileData
    # framebuffer-alpha asks for the alpha channel that lets the cleared
    # background be see-through rather than grey.
    loadPrcFileData("", "window-title Johnny\nhardware-animated-vertices false\n"
                        "framebuffer-alpha true")
    from direct.showbase.ShowBase import ShowBase
    from panda3d.core import Vec4, WindowProperties
    from avatar import canned, scene as scene_mod, wake

    base = ShowBase()
    # A desktop presence, not an application window: no title bar, no frame,
    # and the desktop showing through behind him. Escape is the only way out,
    # because an undecorated window has no close button.
    chrome = WindowProperties()
    chrome.set_undecorated(True)
    base.win.request_properties(chrome)
    base.win.set_clear_color(Vec4(0.0, 0.0, 0.0, 0.0))
    scene = scene_mod.AvatarScene(base)
    voice = voice_client.VoiceClient()
    machine = states.AvatarApp(scene=scene, canned=canned.CannedVoice())

    try:
        listener = wake.WakeListener()
    except FileNotFoundError as exc:
        listener = None
        print(f"{exc}\nPress W in the window to wake him.", file=sys.stderr)

    runtime = Runtime(base, scene, machine, voice=voice, listener=listener)
    # Alongside the voice worker's much longer warm-up; `say` covers until then.
    threading.Thread(target=voice_client.start_speaker, name="mavis-speaker",
                     daemon=True).start()
    runtime.start()
    try:
        base.run()
    finally:
        runtime.stop()
        voice.stop()
        voice_client.stop_speaker()
    return 0


if __name__ == "__main__":
    sys.exit(main())
