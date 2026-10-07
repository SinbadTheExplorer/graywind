"""The committed CC BY mech (the reel's model) as a drop-in."""
import pytest
from panda3d.core import loadPrcFileData

loadPrcFileData("", "window-type none\naudio-library-name null\n"
                    "hardware-animated-vertices false")

from direct.showbase.ShowBase import ShowBase  # noqa: E402

from avatar import portal, scene, stage  # noqa: E402


@pytest.fixture(scope="module")
def base():
    b = ShowBase()
    yield b
    b.destroy()


@pytest.fixture(scope="module")
def mech(base):
    sc = scene.AvatarScene(base, "mech-bust", portal=portal.Screen())
    yield sc
    sc._teardown()


def test_mech_is_registered_with_its_licence_credit():
    reg = scene.all_avatars()
    assert "mech-bust" in scene.available_avatars(reg)
    assert reg["mech-bust"]["credit"] == 'Model: "Mech bust" by Just8 (CC BY 4.0)'


def test_mech_loads_all_meshes_rigged_and_animated(mech):
    """Before tools/fix_sketchfab_glb it loaded ZERO meshes (they sat beside
    the skeleton) or died with KeyError (five skins on one root)."""
    assert mech.actor.find_all_matches("**/+GeomNode").get_num_paths() == 5
    assert mech.actor.get_anim_names() == ["anim"]
    # Behind the glass it plays its clip (the reel is an "animated fbx"),
    # with the look layered on the neck and head rather than replacing them.
    assert mech.animated
    assert mech.look.driven == ["neck_3_04", "neck_4_05", "head_06"]
    assert type(mech.mouth).__name__ == "_JawMouth"


def test_mech_jaw_hinges_about_the_heads_left_right_axis(mech):
    """`p` (the inspector's old guess) skewed the jaw sideways."""
    joint = mech.actor.expose_joint(None, "modelRoot", "jaw_07")
    axis = {"h": (0, 0, 1), "p": (1, 0, 0), "r": (0, 1, 0)}[mech.config["mouth"]["axis"]]
    world = mech.base.render.get_relative_vector(joint, axis).normalized()
    assert abs(world[0]) > 0.95


def test_studio_env_map_is_lit_from_above():
    """Metal reflects this; overhead must be the brightest direction."""
    env = stage.studio_env_map(size=16)
    up = env.cubemap.get_ram_image_as("RGB")
    face_bytes = 16 * 16 * 3

    def mean(face):
        chunk = bytes(up)[face * face_bytes:(face + 1) * face_bytes]
        return sum(chunk) / len(chunk)

    assert mean(4) == max(mean(f) for f in range(6))     # +z, overhead


def test_portal_framing_is_per_model(mech):
    # The largest close-up that keeps its eyes inside the glass from every
    # seat (tests/test_portal_eyes_in_view.py); 1.15 cut them off live. 1.45
    # held while the clip was frozen; with the shake playing and his head
    # turning to look DOWN at a seated viewer, 1.75 is the tightest that clears.
    assert mech.config["portal_framing"] == 1.75
    assert scene._EXTRA_KEYS >= {"portal_framing", "portal_rise"}


def test_the_look_rides_on_top_of_the_shake(mech):
    """controlJoint detaches a joint from its clip. The look takes the neck
    and head, so it has to replay the clip into them -- if it did not, the
    head would freeze while the rest of the bust kept shaking."""
    head = mech.actor.expose_joint(None, "modelRoot", "head_06")
    # Measured from the last joint the clip still owns outright, so only the
    # three driven joints (neck_3, neck_4, head) count.
    above = mech.actor.expose_joint(None, "modelRoot", "neck_2_03")
    poses = []
    for frame in (0, 308):
        mech.actor.pose("anim", frame)
        mech.face(10.0, -5.0)
        mech.face(10.0, -5.0)
        poses.append(head.get_quat(above))
    a, b = poses[0].get_hpr(), poses[1].get_hpr()
    assert max(abs(a[i] - b[i]) for i in range(3)) > 2.0, (
        "the clip no longer moves the head")
