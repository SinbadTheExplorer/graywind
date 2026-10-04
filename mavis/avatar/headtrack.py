"""Find the viewer's eyes in the webcam, continuously, off the render thread.

Detection is OpenCV's YuNet (`cv2.FaceDetectorYN`), a 230KB face model that
also returns both eye centres. MediaPipe would do the same job, but its wheels
trail new Python releases by months and the avatar runs on whatever Python
Homebrew ships; opencv-python publishes abi3 wheels that install on any 3.x.

Threading: the camera must be OPENED on the main thread. On macOS, OpenCV's
AVFoundation backend asks for camera permission on open, and the prompt needs
the main run loop -- opened from a worker it fails with "can not spin main run
loop from other thread" and simply never gets a frame. Reading frames from a
worker afterwards is fine. Hence `open_camera()` is separate from `start()`.

Anything that goes wrong -- no camera, permission refused, no OpenCV -- leaves
`error` set and the tracker reporting no face, which `portal.EyeSmoother`
turns into a centred, still view. The avatar must never die because the
webcam did.
"""
import threading
import time
from pathlib import Path

from avatar import portal

MODEL_PATH = (Path(__file__).resolve().parent.parent
              / "assets" / "headtrack" / "face_detection_yunet_2023mar.onnx")
# Detection runs on a downscaled copy. YuNet finds a face at arm's length in
# 320px comfortably, and it is the per-frame cost that sets tracking latency.
DETECT_WIDTH = 320
SCORE_THRESHOLD = 0.75


def open_camera(index: int = 0):
    """Open the webcam ON THE CALLING (main) THREAD. Returns (capture, error)."""
    try:
        import cv2
    except ImportError as exc:
        return None, f"head tracking off: OpenCV is not installed ({exc})"
    cap = cv2.VideoCapture(index)
    if not cap.isOpened():
        return None, ("head tracking off: no camera, or camera access was "
                      "refused (System Settings > Privacy & Security > Camera)")
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 360)
    return cap, None


def make_detector(model_path: Path = MODEL_PATH):
    import cv2
    if not Path(model_path).exists():
        raise FileNotFoundError(f"face model missing at {model_path}")
    return cv2.FaceDetectorYN.create(str(model_path), "", (DETECT_WIDTH, 180),
                                     SCORE_THRESHOLD, 0.3, 50)


def best_face(faces):
    """The largest confident face row, or None.

    YuNet rows are [x, y, w, h, right_eye(x, y), left_eye(x, y), nose(x, y),
    right_mouth(x, y), left_mouth(x, y), score]. Largest, not most confident:
    with two people in frame, the one nearest the screen is the one the
    window should be drawn for.
    """
    if faces is None or len(faces) == 0:
        return None
    return max(faces, key=lambda row: row[2] * row[3])


def eye_from_frame(detector, frame, screen: portal.Screen):
    """Detect on one BGR frame and return the eye position in metres, or None."""
    import cv2
    h, w = frame.shape[:2]
    scale = DETECT_WIDTH / float(w)
    small = cv2.resize(frame, (DETECT_WIDTH, max(1, int(round(h * scale)))))
    detector.setInputSize((small.shape[1], small.shape[0]))
    _ok, faces = detector.detect(small)
    face = best_face(faces)
    if face is None:
        return None
    right = (face[4] / scale, face[5] / scale)
    left = (face[6] / scale, face[7] / scale)
    return portal.eye_from_landmarks(right, left, (w, h), screen)


class HeadTracker:
    """Reads the camera on a daemon thread and keeps the latest raw eye."""

    def __init__(self, capture, screen: portal.Screen, detector=None):
        self._cap = capture
        self.screen = screen
        self._detector = detector
        self._lock = threading.Lock()
        self._latest = None         # (eye or None, monotonic time)
        self._stop = threading.Event()
        self._thread = None
        self.error = None
        self.fps = 0.0

    def start(self) -> None:
        if self._cap is None:
            return
        if self._detector is None:
            try:
                self._detector = make_detector()
            except Exception as exc:    # missing model, broken OpenCV build
                self.error = f"head tracking off: {exc}"
                return
        self._thread = threading.Thread(target=self._run, name="mavis-headtrack",
                                        daemon=True)
        self._thread.start()

    def latest(self):
        """(eye or None, timestamp) of the newest frame, or (None, None)."""
        with self._lock:
            return self._latest or (None, None)

    def _run(self) -> None:
        frames, window_start = 0, time.monotonic()
        misses = 0
        while not self._stop.is_set():
            ok, frame = self._cap.read()
            if not ok or frame is None:
                misses += 1
                if misses > 60:
                    self.error = "head tracking off: the camera stopped sending frames"
                    with self._lock:
                        self._latest = (None, time.monotonic())
                    return
                time.sleep(0.02)
                continue
            misses = 0
            try:
                eye = eye_from_frame(self._detector, frame, self.screen)
            except Exception as exc:
                self.error = f"head tracking off: {type(exc).__name__}: {exc}"
                return
            with self._lock:
                self._latest = (eye, time.monotonic())
            frames += 1
            now = time.monotonic()
            if now - window_start >= 1.0:
                self.fps = frames / (now - window_start)
                frames, window_start = 0, now

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        if self._cap is not None:
            self._cap.release()
