"""Portal-mode maths: the window must stay a window from any eye."""
import math

import pytest
from panda3d.core import NodePath, PerspectiveLens, Point2, Point3

from avatar import portal

SCREEN = portal.Screen(width=0.302, height=0.196)


def _project(eye, world_point, screen=SCREEN):
    """Film coordinates of `world_point` through the off-axis lens from `eye`."""
    lens = PerspectiveLens()
    camera = NodePath("camera")
    portal.apply_off_axis(camera, lens, eye, screen)
    rel = Point3(*world_point) - camera.get_pos()
    film = Point2()
    assert lens.project(Point3(rel), film), f"{world_point} not in view from {eye}"
    return film


EYES = [
    (0.0, -0.6, 0.0),
    (-0.25, -0.6, 0.05),
    (0.3, -0.45, -0.1),
    (0.05, -1.2, 0.2),
    (-0.1, -0.3, -0.15),
]


@pytest.mark.parametrize("eye", EYES)
def test_screen_corners_land_on_film_corners_from_any_eye(eye):
    """THE property: the glass's edges are the image's edges, wherever you are.

    If this fails the room no longer lines up with the bezel and the illusion
    reads as a picture sliding about inside a frame.
    """
    w, h = SCREEN.width / 2.0, SCREEN.height / 2.0
    for corner, expected in (((-w, 0, h), (-1, 1)), ((w, 0, h), (1, 1)),
                             ((-w, 0, -h), (-1, -1)), ((w, 0, -h), (1, -1))):
        film = _project(eye, corner)
        assert film[0] == pytest.approx(expected[0], abs=1e-4)
        assert film[1] == pytest.approx(expected[1], abs=1e-4)


def test_a_point_on_the_glass_never_moves():
    """Anything AT the screen plane is pinned to the same pixel for all eyes."""
    point = (0.07, 0.0, -0.03)
    films = [_project(eye, point) for eye in EYES]
    for film in films[1:]:
        assert film[0] == pytest.approx(films[0][0], abs=1e-4)
        assert film[1] == pytest.approx(films[0][1], abs=1e-4)


def test_things_behind_the_glass_move_with_the_eye():
    """Parallax direction: lean left and a point behind the glass slides LEFT
    across the window -- you see further round to its right."""
    deep = (0.0, 0.4, 0.0)
    centre = _project((0.0, -0.6, 0.0), deep)
    left = _project((-0.2, -0.6, 0.0), deep)
    assert left[0] < centre[0] - 0.1


def test_off_axis_rejects_an_eye_behind_the_screen():
    with pytest.raises(ValueError):
        portal.off_axis((0, 0.1, 0), SCREEN)


def test_eye_from_landmarks_centred_face_is_straight_ahead():
    # 640x360 frame, eyes symmetric about the centre column, at the centre row.
    eye = portal.eye_from_landmarks((300, 180), (340, 180), (640, 360), SCREEN)
    x, y, z = eye
    assert x == pytest.approx(0.0, abs=1e-9)
    # The webcam sits above the screen, so an eye level with the CAMERA is
    # above the screen's centre by half its height plus the camera's offset.
    assert z == pytest.approx(SCREEN.height / 2 + SCREEN.webcam_above)
    focal = 320 / math.tan(math.radians(SCREEN.webcam_hfov_deg) / 2)
    assert y == pytest.approx(-focal * portal.IPD_M / 40.0)


def test_eye_from_landmarks_image_right_is_the_viewers_left():
    """The camera faces the viewer: a face in the image's right half is a
    viewer sitting to their own LEFT of the screen, i.e. -x. Getting this
    backwards makes the room swing the wrong way and the effect inverts."""
    eye = portal.eye_from_landmarks((480, 180), (520, 180), (640, 360), SCREEN)
    assert eye[0] < -0.05
    mirrored = portal.Screen(mirrored=True)
    eye_m = portal.eye_from_landmarks((480, 180), (520, 180), (640, 360), mirrored)
    assert eye_m[0] > 0.05


def test_eye_from_landmarks_closer_face_reads_nearer():
    far = portal.eye_from_landmarks((310, 180), (330, 180), (640, 360), SCREEN)
    near = portal.eye_from_landmarks((280, 180), (360, 180), (640, 360), SCREEN)
    assert -near[1] < -far[1]


def test_eye_from_landmarks_rejects_degenerate_input():
    assert portal.eye_from_landmarks((300, 180), (300, 180), (640, 360), SCREEN) is None


def test_clamp_eye_keeps_it_in_front_and_near():
    assert portal.clamp_eye((0, 0.3, 0), SCREEN)[1] == pytest.approx(-0.25)
    assert portal.clamp_eye((0, -9, 0), SCREEN)[1] == pytest.approx(-1.6)
    assert abs(portal.clamp_eye((5, -0.6, 0), SCREEN)[0]) < 1.0


def test_screen_from_env_reads_centimetres():
    s = portal.screen_from_env({"MAVIS_SCREEN_CM": "34.5x22.4",
                                "MAVIS_WEBCAM_HFOV": "70",
                                "MAVIS_WEBCAM_MIRRORED": "1"})
    assert (s.width, s.height) == (pytest.approx(0.345), pytest.approx(0.224))
    assert s.webcam_hfov_deg == 70.0 and s.mirrored


@pytest.mark.parametrize("bad", ["34.5", "axb", "-3x2", "0x10"])
def test_screen_from_env_rejects_garbage(bad):
    with pytest.raises(ValueError):
        portal.screen_from_env({"MAVIS_SCREEN_CM": bad})


def test_gaze_turns_toward_the_viewer_and_is_clamped():
    assert portal.gaze_heading((0.2, -0.6, 0), 0.3) > 0
    assert portal.gaze_heading((-0.2, -0.6, 0), 0.3) < 0
    assert portal.gaze_heading((0.0, -0.6, 0), 0.3) == 0
    assert portal.gaze_heading((5.0, -0.6, 0), 0.3) == pytest.approx(9.0)


def test_one_euro_holds_still_input_still_and_follows_a_jump():
    f = portal.OneEuroFilter()
    t = 0.0
    for _ in range(30):
        out = f(1.0, t)
        t += 1 / 30
    assert out == pytest.approx(1.0)
    # Jitter of +/-2mm while still is heavily damped...
    outs = []
    for i in range(30):
        outs.append(f(1.0 + (0.002 if i % 2 else -0.002), t))
        t += 1 / 30
    assert max(outs) - min(outs) < 0.002
    # ...but a real move is followed within a few hundred ms.
    for _ in range(10):
        out = f(1.2, t)
        t += 1 / 30
    assert out > 1.15


def test_smoother_holds_through_a_blink_then_glides_home():
    s = portal.EyeSmoother(SCREEN)
    seen = (0.15, -0.5, 0.05)
    t = 0.0
    for _ in range(20):
        s.update(seen, t)
        t += 1 / 30
    held = s.update(None, t + 0.3)
    assert held == pytest.approx(s.update(seen, t), abs=0.02)

    s2 = portal.EyeSmoother(SCREEN)
    for i in range(20):
        s2.update(seen, i / 30)
    last = 19 / 30
    mid = s2.update(None, last + s2.HOLD + s2.RETURN / 2)
    home = s2.update(None, last + s2.HOLD + s2.RETURN + 1.0)
    assert home == pytest.approx(SCREEN.nominal_eye)
    assert 0.0 < mid[0] < seen[0]           # on its way, not snapped


def test_smoother_reacquires_without_a_jump():
    s = portal.EyeSmoother(SCREEN)
    for i in range(20):
        s.update((0.15, -0.5, 0.05), i / 30)
    t = 19 / 30 + s.HOLD + s.RETURN + 1.0
    shown = s.update(None, t)               # fully home
    back = s.update((0.15, -0.5, 0.05), t + 1 / 30)
    # One frame after the face reappears the view has moved toward it, but
    # not all the way: no snap.
    assert shown[0] < back[0] < 0.15


def test_gaze_pitch_looks_down_at_a_viewer_below_and_is_clamped():
    assert portal.gaze_pitch((0, -0.6, 0.0), 0.18, 0.05) < 0      # viewer below
    assert portal.gaze_pitch((0, -0.6, 0.3), 0.18, 0.05) > 0      # viewer above
    assert portal.gaze_pitch((0, -0.6, -5.0), 0.18, 0.05) == pytest.approx(-10.0)
