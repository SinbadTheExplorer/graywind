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

MAVIS_PORTAL=1 stands him behind the glass instead (see `avatar.portal`):
full screen, a room behind him, and the view redrawn from wherever the
webcam sees your eyes. T pauses the tracking, to compare with and without.
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

from avatar import (brain, capture, dismiss, lipsync, portal, states, stt,
                    voice_client)

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


class Runtime:
    def __init__(self, base, scene, machine, voice=None, listener=None,
                 tracker=None):
        self.base = base
        self.scene = scene
        self.machine = machine
        self.voice = voice
        self.listener = listener
        # Portal mode only: the webcam head tracker and the smoothing between
        # it and the lens. Both None in the overlay, and _tick skips them.
        self.tracker = tracker
        self._smoother = (portal.EyeSmoother(scene.portal)
                          if getattr(scene, "portal", None) is not None else None)
        self._eye_stamp = None
        self._tracking = True
        self._tracker_error_shown = False
        self._inbox = queue.Queue()
        self._manual_wake = threading.Event()
        self._stopping = threading.Event()
        self._mouth = None          # (envelope, start) while audio plays
        self._mouth_open = False
        base.taskMgr.add(self._tick, "mavis-runtime")
        base.accept("w", self._manual_wake.set)
        base.accept("escape", base.userExit)
        if self._smoother is not None:
            base.accept("t", self._toggle_tracking)

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
        if self._smoother is not None:
            self._follow_eye()
        mouth = self._mouth
        if mouth is not None:
            env, start = mouth
            self.scene.set_mouth(lipsync.amount_at(env, time.monotonic() - start))
            self._mouth_open = True
        elif self._mouth_open:
            self.scene.set_mouth(0.0)
            self._mouth_open = False
        return task.cont

    def _follow_eye(self) -> None:
        """Feed the newest webcam reading through the smoother into the lens.

        A reading is fed once, at its own capture time. Between readings the
        smoother is asked with None at the current time, which it treats as
        "nothing new" for HOLD seconds and only then as "face gone" -- so the
        render rate and the camera rate never need to agree.
        """
        now = time.monotonic()
        eye, stamp = (None, None)
        if self.tracker is not None and self._tracking:
            eye, stamp = self.tracker.latest()
            error = getattr(self.tracker, "error", None)
            if error and not self._tracker_error_shown:
                self._tracker_error_shown = True
                self.scene.show_notice(error)
        if stamp is not None and stamp != self._eye_stamp:
            self._eye_stamp = stamp
            view = self._smoother.update(eye, stamp)
        else:
            view = self._smoother.update(None, now)
        self.scene.look_from(view)

    def _toggle_tracking(self) -> None:
        self._tracking = not self._tracking
        self.scene.show_notice("" if self._tracking else "head tracking paused (T)")

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
        self._mouth = (env, time.monotonic())
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

    def _voice(self, text: str) -> str:
        """Johnny-voiced wav for `text`, or the plain scaffold if VC fails."""
        workdir = tempfile.mkdtemp(prefix="mavis-")
        scaffold = os.path.join(workdir, "scaffold.wav")
        final = os.path.join(workdir, "johnny.wav")
        try:
            voice_client.say_to_wav(text, scaffold)
            if self.voice is not None and self.voice.convert(scaffold, final):
                return final
            if self.voice is not None and self.voice.last_error:
                reason = self.voice.last_error
                self.on_render(lambda: self.machine.note_degraded(reason))
            return scaffold
        except BaseException:
            shutil.rmtree(workdir, ignore_errors=True)
            raise

    def _settle_notice(self) -> None:
        """Clear a stale error, but keep saying so while the voice is degraded.

        Render thread. A notice left up after the fault has passed claims
        something is broken that is not -- as misleading as no notice at all.
        """
        if self.voice is not None and self.voice.degraded:
            self.machine.note_degraded(self.voice.last_error or "worker unavailable")
        else:
            self.scene.show_notice("")

    async def _answer(self, question: str) -> tuple[str, str]:
        """The spoken wav and the exact text it says.

        The text is returned rather than re-derived so the caption is the
        answer itself, not a transcription of his audio -- captioning our own
        speech through STT would add both latency and a way to be wrong.
        """
        answer = await brain.ask(question)
        if not answer:
            raise brain.BrainError("the backend returned an empty answer")
        wav = await asyncio.to_thread(self._voice, answer)
        return wav, answer

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
                wav, answer_text = await pending
            except brain.BrainError as exc:
                self.on_render(lambda: self.machine.on_failure(str(exc)))
                continue
            self.on_render(lambda: (self._settle_notice(),
                                    self.scene.show_caption(answer_text),
                                    self.machine.on_answer_ready()))
            try:
                await asyncio.to_thread(self.say, wav)
            finally:
                # rmtree FIRST: it cannot raise, and on_render can. Escape
                # pressed mid-sentence sets _stopping, the render loop is
                # already gone, and on_render gives up with RuntimeError --
                # which would otherwise skip this cleanup and replace whatever
                # `say` was propagating with a shutdown error.
                shutil.rmtree(os.path.dirname(wav), ignore_errors=True)
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

    from avatar import headtrack

    screen = portal.screen_from_env() if portal_requested() else None
    base = ShowBase()
    chrome = WindowProperties()
    if screen is None:
        # A desktop presence, not an application window: no title bar, no
        # frame, and the desktop showing through behind him. Escape is the
        # only way out, because an undecorated window has no close button.
        chrome.set_undecorated(True)
        base.win.request_properties(chrome)
        base.win.set_clear_color(Vec4(0.0, 0.0, 0.0, 0.0))
    else:
        # Behind the glass the window IS the glass: it has to cover exactly
        # the physical screen MAVIS_SCREEN_CM describes, or the frustum is
        # drawn for a window that is not there and the room shears.
        chrome.set_fullscreen(True)
        chrome.set_size(base.pipe.get_display_width(),
                        base.pipe.get_display_height())
        base.win.request_properties(chrome)
        base.win.set_clear_color(Vec4(0.0, 0.0, 0.0, 1.0))
    scene = scene_mod.AvatarScene(base, portal=screen)
    voice = voice_client.VoiceClient()
    machine = states.AvatarApp(scene=scene, canned=canned.CannedVoice())

    try:
        listener = wake.WakeListener()
    except FileNotFoundError as exc:
        listener = None
        print(f"{exc}\nPress W in the window to wake him.", file=sys.stderr)

    tracker = None
    if screen is not None:
        # Opened HERE, on the main thread, before base.run(): see headtrack.
        capture_dev, error = headtrack.open_camera()
        tracker = headtrack.HeadTracker(capture_dev, screen)
        tracker.error = error
        tracker.start()
        if tracker.error:
            print(tracker.error, file=sys.stderr)

    runtime = Runtime(base, scene, machine, voice=voice, listener=listener,
                      tracker=tracker)
    runtime.start()
    try:
        base.run()
    finally:
        runtime.stop()
        voice.stop()
        if tracker is not None:
            tracker.stop()
    return 0


def portal_requested(environ=None) -> bool:
    env = os.environ if environ is None else environ
    return env.get("MAVIS_PORTAL", "") not in ("", "0", "false")


if __name__ == "__main__":
    sys.exit(main())
