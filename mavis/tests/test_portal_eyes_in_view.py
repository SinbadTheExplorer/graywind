"""The mech's eyes never leave the window, wherever the viewer sits.

The first live run had his eye lights cut off by the top of the glass when
he tracked the viewer. A face cropped by the frame's edge is the one crop
that breaks the illusion -- the reel crops the mech's crest, never its eyes.
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

SCREENS = {"air-13": portal.Screen(width=0.290, height=0.189),
           "default": portal.Screen()}


@pytest.fixture(scope="module")
def base():
    b = ShowBase()
    yield b
    b.destroy()


def _eye_lights(sc):
    """World positions of the glowing parts on his face: the eye lights.

    Every glow vertex in the head's upper three-quarters -- the chest lamp
    below the chin may crop, as it does in the reel.
    """
    head = sc.actor.find(f"**/{sc.config['head_mesh']}")
    low, high = head.get_tight_bounds(sc.base.render)
    floor = low[2] + 0.25 * (high[2] - low[2])
    points = []
    for np_ in sc.actor.find_all_matches("**/+GeomNode"):
        if "glow" not in np_.name:
            continue
        mat = np_.get_mat(sc.base.render)
        node = np_.node()
        for i in range(node.get_num_geoms()):
            data = node.get_geom(i).get_vertex_data().animate_vertices(
                True, Thread.get_current_thread())
            reader = GeomVertexReader(data, "vertex")
            while not reader.is_at_end():
                p = mat.xform_point(reader.get_data3())
                if p[2] >= floor:
                    points.append(p)
    assert points, "found no eye lights to check"
    return points


@pytest.mark.parametrize("screen_name", sorted(SCREENS))
def test_the_mechs_eyes_stay_inside_the_glass(base, screen_name):
    screen = SCREENS[screen_name]
    sc = scene.AvatarScene(base, "mech-bust", portal=screen)
    try:
        margin = MARGIN * screen.height
        worst = None
        for eye in itertools.product(VIEW_X, VIEW_Y, VIEW_Z):
            # Turned fully toward this viewer, as he settles after easing.
            sc.look_from(eye)
            sc.pivot.set_h(sc.gaze)
            sc.pivot.set_p(sc.gaze_p)
            ex, ey, ez = eye
            for p in _eye_lights(sc):
                t = -ey / (p[1] - ey)            # where the sight line meets the glass
                x, z = ex + t * (p[0] - ex), ez + t * (p[2] - ez)
                slack = min(screen.width / 2 - abs(x), screen.height / 2 - abs(z))
                if worst is None or slack < worst[0]:
                    worst = (slack, eye, (round(x, 3), round(z, 3)))
        assert worst[0] >= margin, (
            f"an eye light is {(margin - worst[0]) * 1000:.1f}mm too close to the "
            f"frame's edge, seen from {worst[1]} at {worst[2]} on the glass")
    finally:
        sc._teardown()
