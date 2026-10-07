"""Every model's eyes never leave the window, wherever the viewer sits.

The first live run had the mech's eye lights cut off by the top of the glass
when he tracked the viewer. A face cropped by the frame's edge is the one crop
that breaks the illusion -- the reel crops the mech's crest, never its eyes.

Checked with the clips PLAYING (sampled across every clip the model has) and
the head and eyes turned all the way to each viewer, because the look is
layered on top of the clip and the two add up.
"""
import itertools

import pytest
from panda3d.core import GeomVertexReader, Thread, loadPrcFileData

loadPrcFileData("", "window-type none\naudio-library-name null\n"
                    "hardware-animated-vertices false")

from direct.showbase.ShowBase import ShowBase  # noqa: E402

from avatar import portal, scene  # noqa: E402

# Where a person at a laptop actually sits: a forearm's reach either way,
# leaning in close or sitting back, eyes from well below the screen's centre
# to a little above it.
VIEW_X = (-0.20, 0.0, 0.20)
VIEW_Y = (-0.45, -0.60, -0.85)
VIEW_Z = (-0.15, 0.0, 0.10)
MARGIN = 0.06        # of the window's height: the eyes are never even grazing
FRAMES_PER_CLIP = 8
# Every Nth vertex: the mech's glow alone is 13k vertices, and the eye
# discs are dense enough that a subsample still finds their edges.
STRIDE = 7

SCREENS = {"air-13": portal.Screen(width=0.290, height=0.189),
           "default": portal.Screen()}


@pytest.fixture(scope="module")
def base():
    b = ShowBase()
    yield b
    b.destroy()


def _vertices(sc, np_, keep=lambda p: True):
    mat = np_.get_mat(sc.base.render)
    node = np_.node()
    points = []
    for i in range(node.get_num_geoms()):
        data = node.get_geom(i).get_vertex_data().animate_vertices(
            True, Thread.get_current_thread())
        reader = GeomVertexReader(data, "vertex")
        n = 0
        while not reader.is_at_end():
            p = mat.xform_point(reader.get_data3())
            if n % STRIDE == 0 and keep(p):
                points.append(p)
            n += 1
    return points


def _mech_eyes(sc):
    """The glowing parts in the head's upper three-quarters -- the chest lamp
    below the chin may crop, as it does in the reel."""
    head = sc.actor.find(f"**/{sc.config['head_mesh']}")
    low, high = head.get_tight_bounds(sc.base.render)
    floor = low[2] + 0.25 * (high[2] - low[2])
    points = []
    for np_ in sc.actor.find_all_matches("**/+GeomNode"):
        if "glow" in np_.name:
            points += _vertices(sc, np_, lambda p: p[2] >= floor)
    return points


def _keanu_eyes(sc):
    points = []
    for np_ in sc.actor.find_all_matches("**/eyes/+GeomNode"):
        points += _vertices(sc, np_)
    return points


def _spartan_visor(sc):
    """The visor is part of the helmet mesh: its front, at mid height."""
    helmet = sc.actor.find(f"**/{sc.config['head_mesh']}")
    low, high = helmet.get_tight_bounds(sc.base.render)
    lo_z = low[2] + 0.35 * (high[2] - low[2])
    hi_z = low[2] + 0.75 * (high[2] - low[2])
    front = (low[1] + high[1]) / 2
    return _vertices(sc, helmet,
                     lambda p: lo_z <= p[2] <= hi_z and p[1] <= front)


EYES = {"mech-bust": _mech_eyes, "keanu": _keanu_eyes, "spartan": _spartan_visor}


def _poses(sc):
    """(clip, frame) samples across every clip, or a single still pose."""
    if not sc.animated:
        return [(None, None)]
    poses = []
    for clip in sc.actor.get_anim_names():
        n = sc.actor.get_num_frames(clip)
        poses += [(clip, round(k * (n - 1) / (FRAMES_PER_CLIP - 1)))
                  for k in range(FRAMES_PER_CLIP)]
    return poses


def _hold(sc, clip, frame):
    if clip is None:
        return
    for other in sc.actor.get_anim_names():
        sc.actor.set_control_effect(other, 1.0 if other == clip else 0.0)
    sc.actor.pose(clip, frame)


@pytest.mark.parametrize("screen_name", sorted(SCREENS))
@pytest.mark.parametrize("name", sorted(EYES))
def test_the_eyes_stay_inside_the_glass(base, name, screen_name):
    registry = scene.all_avatars()
    if name not in registry or not scene.model_path(registry[name]).exists():
        pytest.skip(f"{name} is not built on this machine (gitignored)")
    screen = SCREENS[screen_name]
    sc = scene.AvatarScene(base, name, portal=screen, registry=registry)
    try:
        margin = MARGIN * screen.height
        worst = worst_slack(sc, name, screen)
        assert worst[0] >= margin, (
            f"{name}'s eyes come {(margin - worst[0]) * 1000:.1f}mm too close to "
            f"the frame's edge, seen from {worst[1]} during {worst[2]} frame "
            f"{worst[3]}, at {worst[4]} on the glass")
    finally:
        sc._teardown()


def worst_slack(sc, name, screen):
    """(slack, eye, clip, frame, point on glass) for the eye point nearest an
    edge. Slack is metres on the glass; negative is outside the window."""
    worst = None
    for clip, frame in _poses(sc):
        _hold(sc, clip, frame)
        for eye in itertools.product(VIEW_X, VIEW_Y, VIEW_Z):
            # Turned fully toward this viewer, as he settles after easing.
            # Twice: the look converts through the parent joint's frame as
            # last drawn, which the first call has just moved.
            sc.look_from(eye)
            sc.face(sc.gaze, sc.gaze_p)
            sc.face(sc.gaze, sc.gaze_p)
            ex, ey, ez = eye
            points = EYES[name](sc)
            assert points, "found no eyes to check"
            for p in points:
                t = -ey / (p[1] - ey)       # where the sight line meets the glass
                x, z = ex + t * (p[0] - ex), ez + t * (p[2] - ez)
                slack = min(screen.width / 2 - abs(x), screen.height / 2 - abs(z))
                if worst is None or slack < worst[0]:
                    worst = (slack, eye, clip, frame, (round(x, 3), round(z, 3)))
    return worst
