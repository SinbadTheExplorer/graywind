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
    assert mech.animated and mech.actor.get_anim_names() == ["anim"]
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
    assert mech.config["portal_framing"] == 1.15     # the reel's close-up
    assert scene._EXTRA_KEYS >= {"portal_framing", "portal_rise"}
