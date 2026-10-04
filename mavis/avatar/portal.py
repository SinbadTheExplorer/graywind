"""Portal mode: the monitor becomes a window Johnny stands behind.

The trick (the "off-axis projection" in the reel this was built from) is to
stop drawing the scene from a fixed camera and instead draw it from wherever
the viewer's eye actually is, through a frustum whose four edges pass exactly
through the four edges of the physical screen. Move your head left and you
see further round his right shoulder, exactly as you would through glass.

Everything here is in METRES in Panda3D's frame, with the physical screen as
the origin:

    x  -> the viewer's right, along the screen
    y  -> straight into the screen (Johnny is at +y, the viewer at -y)
    z  -> up, along the screen

The maths is pure and windowless so the suite can pin it; the webcam side
lives in `headtrack`, and `scene` owns the nodes this module positions.
"""
import math
import os
from dataclasses import dataclass

# The default display is a 14" MacBook Pro's lit area. Measure yours with a
# ruler -- the effect is only as right as these two numbers -- and set
# MAVIS_SCREEN_CM="30.2x19.6". On a notched Mac in full screen, measure the
# area BELOW the notch: macOS letterboxes full-screen apps under it.
DEFAULT_SCREEN_M = (0.302, 0.196)
# The FaceTime camera sits just above the lit area, centred.
DEFAULT_WEBCAM_ABOVE_M = 0.008
# Where the eye is assumed to be when nobody is tracked: centred, at a normal
# laptop distance. Also the eye the room is FRAMED from.
NOMINAL_EYE_DISTANCE_M = 0.60
# Average adult interpupillary distance. The tracker turns the pixel gap
# between the eyes into a distance with it; being off by a few mm only
# scales the effect slightly.
IPD_M = 0.063
# Horizontal field of view of a MacBook FaceTime HD camera, roughly.
DEFAULT_WEBCAM_HFOV_DEG = 62.0


@dataclass(frozen=True)
class Screen:
    width: float = DEFAULT_SCREEN_M[0]
    height: float = DEFAULT_SCREEN_M[1]
    webcam_above: float = DEFAULT_WEBCAM_ABOVE_M
    webcam_hfov_deg: float = DEFAULT_WEBCAM_HFOV_DEG
    # Flip x if the camera driver hands over a mirrored image. AVFoundation
    # does not, but a virtual camera (Continuity, OBS) can.
    mirrored: bool = False

    @property
    def nominal_eye(self):
        return (0.0, -NOMINAL_EYE_DISTANCE_M, 0.0)


def screen_from_env(environ=None) -> Screen:
    """Screen geometry from MAVIS_SCREEN_CM / MAVIS_WEBCAM_HFOV / MAVIS_WEBCAM_MIRRORED."""
    env = os.environ if environ is None else environ
    width, height = DEFAULT_SCREEN_M
    raw = env.get("MAVIS_SCREEN_CM")
    if raw:
        try:
            w_cm, h_cm = (float(part) for part in raw.lower().split("x"))
        except ValueError:
            raise ValueError(
                f"MAVIS_SCREEN_CM={raw!r} must look like '30.2x19.6'") from None
        if w_cm <= 0 or h_cm <= 0:
            raise ValueError(f"MAVIS_SCREEN_CM={raw!r} must be positive")
        width, height = w_cm / 100.0, h_cm / 100.0
    hfov = float(env.get("MAVIS_WEBCAM_HFOV", DEFAULT_WEBCAM_HFOV_DEG))
    mirrored = env.get("MAVIS_WEBCAM_MIRRORED", "") not in ("", "0", "false")
    return Screen(width=width, height=height, webcam_hfov_deg=hfov,
                  mirrored=mirrored)


def eye_from_landmarks(right_eye, left_eye, image_size, screen: Screen):
    """Where the viewer's eyes are, in metres, from two pixel landmarks.

    `right_eye` / `left_eye` are (u, v) pixels as YuNet reports them (the
    person's own right and left). Returns the midpoint between the eyes in
    the screen frame described at the top of this module, or None if the
    landmarks are degenerate.

    Depth comes from how far apart the eyes are in the image: the pinhole
    model says pixel gap = focal_px * IPD / depth. Turning the head shrinks
    that gap and reads as leaning back -- an accepted error, it only damps
    the effect while the head is turned.

    The camera faces the viewer, so its image-right is the viewer's LEFT:
    x flips. Image v grows downward: z flips too.
    """
    img_w, img_h = image_size
    gap = math.hypot(right_eye[0] - left_eye[0], right_eye[1] - left_eye[1])
    if gap < 1.0 or img_w <= 0 or img_h <= 0:
        return None
    focal_px = (img_w / 2.0) / math.tan(math.radians(screen.webcam_hfov_deg) / 2.0)
    depth = focal_px * IPD_M / gap

    u = (right_eye[0] + left_eye[0]) / 2.0
    v = (right_eye[1] + left_eye[1]) / 2.0
    cam_x = (u - img_w / 2.0) * depth / focal_px    # camera's right
    cam_y = (v - img_h / 2.0) * depth / focal_px    # camera's down

    x = cam_x if screen.mirrored else -cam_x
    z = screen.height / 2.0 + screen.webcam_above - cam_y
    return (x, -depth, z)


def clamp_eye(eye, screen: Screen):
    """Keep a tracked eye physically plausible.

    A misdetection can put the eye behind the screen or a metre to one side;
    the frustum maths would happily render that and the room would fold
    inside out for a frame. Clamp rather than reject so a borderline but real
    reading still moves the view.
    """
    x, y, z = eye
    distance = min(max(-y, 0.25), 1.6)
    reach = max(screen.width, 0.3) * 1.5
    x = min(max(x, -reach), reach)
    z = min(max(z, -reach), reach)
    return (x, -distance, z)


def off_axis(eye, screen: Screen):
    """Lens settings that make the screen a window, seen from `eye`.

    Returns (camera_pos, focal_length, film_size, film_offset). With the focal
    length equal to the eye's distance from the screen plane, the film plane
    IS the screen plane: the film is the screen's own size, and the offset is
    where the screen's centre sits relative to the eye. This is Kooima's
    generalised perspective projection for the special case of a screen
    square-on to the view axis, which a laptop always is to its own camera.
    """
    x, y, z = eye
    distance = -y
    if distance <= 0:
        raise ValueError(f"eye {eye} is not in front of the screen")
    return ((x, y, z), distance, (screen.width, screen.height), (-x, -z))


def apply_off_axis(camera, lens, eye, screen: Screen, near=0.02, far=20.0):
    """Point a Panda3D camera + PerspectiveLens through the screen from `eye`."""
    pos, focal, film, offset = off_axis(eye, screen)
    camera.set_pos(*pos)
    camera.set_hpr(0, 0, 0)
    lens.set_film_size(*film)
    lens.set_focal_length(focal)
    lens.set_film_offset(*offset)
    lens.set_near_far(min(near, focal * 0.5), far)


def gaze_heading(eye, subject_y: float, limit_deg: float = 9.0) -> float:
    """Degrees to turn the actor so he faces the viewer, clamped small.

    Positive H turns a Panda3D model to ITS left, which is the viewer's right
    as he faces out of the screen -- so a viewer at +x needs +H. Clamped
    because a man who swivels to follow you round the room reads as a
    turret, not a person.
    """
    x, y, _z = eye
    run = subject_y - y
    if run <= 0:
        return 0.0
    angle = math.degrees(math.atan2(x, run))
    return max(-limit_deg, min(limit_deg, angle))


class OneEuroFilter:
    """Casiez et al.'s 1-euro filter (CHI 2012), one scalar channel.

    Webcam landmarks jitter by a pixel or two every frame, which at the
    screen is a visible shimmer; a plain low-pass that kills it adds a lag
    you feel as the room "swimming" after your head. The 1-euro filter
    adapts: heavy smoothing when still, almost none when moving fast.
    """

    def __init__(self, min_cutoff=1.2, beta=0.4, d_cutoff=1.0):
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.d_cutoff = d_cutoff
        self._x = None
        self._dx = 0.0
        self._t = None

    @staticmethod
    def _alpha(cutoff, dt):
        tau = 1.0 / (2.0 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def __call__(self, value: float, t: float) -> float:
        if self._x is None or self._t is None or t <= self._t:
            self._x, self._t = value, t
            return value
        dt = t - self._t
        dx = (value - self._x) / dt
        a_d = self._alpha(self.d_cutoff, dt)
        self._dx = a_d * dx + (1.0 - a_d) * self._dx
        cutoff = self.min_cutoff + self.beta * abs(self._dx)
        a = self._alpha(cutoff, dt)
        self._x = a * value + (1.0 - a) * self._x
        self._t = t
        return self._x


class EyeSmoother:
    """Three 1-euro channels, plus a glide home when the face is lost."""

    # Seconds without a face before the view starts drifting back to centre,
    # and how long that drift takes. A blink or a hand across the face must
    # not snap the room; walking away should settle it.
    HOLD = 0.8
    RETURN = 1.5

    def __init__(self, screen: Screen):
        self.screen = screen
        self._filters = [OneEuroFilter() for _ in range(3)]
        self._last = screen.nominal_eye
        self._shown = self._last
        self._last_seen = None
        self._lost_from = None

    def update(self, eye, t: float):
        """Feed a raw eye (or None for no face) at time t; get the eye to render."""
        if eye is not None:
            eye = clamp_eye(eye, self.screen)
            if self._lost_from is not None:
                # Re-seed every channel AT THE VIEW ON SCREEN, a frame ago, so
                # the room eases from where it drifted to rather than jumping
                # to the face the instant it reappears.
                self._filters = [OneEuroFilter() for _ in range(3)]
                for f, v in zip(self._filters, self._shown):
                    f(v, t - 1.0 / 30.0)
                self._lost_from = None
            self._last = tuple(f(v, t) for f, v in zip(self._filters, eye))
            self._last_seen = t
            self._shown = self._last
            return self._last

        if self._last_seen is None or t - self._last_seen < self.HOLD:
            self._shown = self._last
            return self._last
        if self._lost_from is None:
            # Timed from when the face actually went, not from whenever this
            # was first asked: the glide must not depend on the polling rate.
            self._lost_from = (self._last_seen + self.HOLD, self._last)
        started, origin = self._lost_from
        k = min(1.0, (t - started) / self.RETURN)
        k = k * k * (3.0 - 2.0 * k)
        home = self.screen.nominal_eye
        self._shown = tuple(o + (h - o) * k for o, h in zip(origin, home))
        return self._shown
