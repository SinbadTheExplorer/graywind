"""The webcam tracker, with the camera and detector faked out."""
import time

import numpy as np
import pytest

from avatar import headtrack, portal

SCREEN = portal.Screen()


def _face_row(cx, cy, gap, size=60.0, score=0.95):
    """A YuNet-shaped row for a face centred at (cx, cy) in DETECT pixels."""
    return np.array([cx - size / 2, cy - size / 2, size, size,
                     cx - gap / 2, cy, cx + gap / 2, cy,
                     cx, cy + 8, cx - 10, cy + 20, cx + 10, cy + 20, score],
                    dtype=np.float32)


class FakeDetector:
    def __init__(self, faces):
        self.faces = faces
        self.sizes = []

    def setInputSize(self, size):
        self.sizes.append(size)

    def detect(self, image):
        return 1, self.faces


class FakeCapture:
    def __init__(self, frames=None):
        self.frames = frames
        self.released = False

    def read(self):
        time.sleep(0.005)
        return True, np.zeros((360, 640, 3), np.uint8)

    def release(self):
        self.released = True


def test_best_face_prefers_the_nearest_person():
    small = _face_row(100, 90, 20, size=30)
    big = _face_row(200, 90, 30, size=80)
    assert headtrack.best_face(np.stack([small, big]))[2] == 80
    assert headtrack.best_face(None) is None


def test_eye_from_frame_scales_detections_back_to_full_frame():
    pytest.importorskip("cv2")
    # Detection runs at 320 wide on a 640-wide frame: a centred face found at
    # (160, 90) in the small image is the frame's centre.
    det = FakeDetector(np.stack([_face_row(160, 90, 20)]))
    eye = headtrack.eye_from_frame(det, np.zeros((360, 640, 3), np.uint8), SCREEN)
    assert det.sizes[-1] == (320, 180)
    assert eye[0] == pytest.approx(0.0, abs=1e-6)
    # 20px gap at half scale is 40px at full scale.
    same = portal.eye_from_landmarks((300, 180), (340, 180), (640, 360), SCREEN)
    assert eye == pytest.approx(same)


def test_tracker_publishes_readings_and_stops_cleanly():
    pytest.importorskip("cv2")
    cap = FakeCapture()
    tracker = headtrack.HeadTracker(cap, SCREEN,
                                    detector=FakeDetector(np.stack([_face_row(160, 90, 20)])))
    tracker.start()
    deadline = time.monotonic() + 2.0
    while tracker.latest()[1] is None and time.monotonic() < deadline:
        time.sleep(0.01)
    eye, stamp = tracker.latest()
    tracker.stop()
    assert stamp is not None and eye is not None
    assert cap.released
    assert tracker.error is None


def test_tracker_without_a_camera_is_inert_not_fatal():
    tracker = headtrack.HeadTracker(None, SCREEN)
    tracker.start()
    assert tracker.latest() == (None, None)
    tracker.stop()


def test_bundled_face_model_loads_and_finds_nothing_in_black():
    cv2 = pytest.importorskip("cv2")
    assert headtrack.MODEL_PATH.exists(), "assets/headtrack model missing"
    det = headtrack.make_detector()
    assert headtrack.eye_from_frame(det, np.zeros((360, 640, 3), np.uint8),
                                    SCREEN) is None
    assert cv2 is not None
