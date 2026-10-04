"""Switching models at runtime, and drop-in models from assets/avatar/extra/."""
import json

import pytest
from panda3d.core import loadPrcFileData

loadPrcFileData("", "window-type none\naudio-library-name null\n"
                    "hardware-animated-vertices false")

from direct.showbase.ShowBase import ShowBase  # noqa: E402
from panda3d.core import LightAttrib  # noqa: E402

from avatar import portal, scene  # noqa: E402

JONNY_BAM = scene.ASSET_DIR / "jonny_fixed.bam"


def _drop_in(root, name, **spec):
    folder = root / name
    folder.mkdir(parents=True)
    spec.setdefault("model", "model.bam")
    spec.setdefault("credit", f"Model: {name} by somebody (CC BY)")
    if spec["model"] == "model.bam":
        (folder / "model.bam").write_bytes(JONNY_BAM.read_bytes())
    (folder / "avatar.json").write_text(json.dumps(spec))
    return folder


@pytest.fixture(scope="module")
def extra(tmp_path_factory):
    root = tmp_path_factory.mktemp("extra")
    # A second, mouth-less copy of the CC-BY model: enough to prove a swap
    # without needing the gitignored keanu.
    _drop_in(root, "twin", head_mesh="Wolf3D_Head")
    return root


@pytest.fixture(scope="module")
def registry(extra):
    reg = scene.all_avatars(extra)
    # keanu is gitignored and may not exist; keep the order test hermetic.
    reg.pop("keanu", None)
    return reg


@pytest.fixture(scope="module")
def base():
    b = ShowBase()
    yield b
    b.destroy()


def _lights_on_render(base):
    attrib = base.render.get_attrib(LightAttrib)
    return 0 if attrib is None else attrib.get_num_on_lights()


def test_drop_in_folder_joins_the_registry(registry):
    assert "twin" in registry
    assert registry["twin"]["mouth"] == {"kind": "none"}
    assert scene.available_avatars(registry) == ["jonny", "twin"]


@pytest.mark.parametrize("spec, reason", [
    ({"credit": None}, "missing credit"),
    ({"model": "absent.glb"}, "missing file"),
    ({"colour": "red"}, "unknown key"),
])
def test_a_bad_drop_in_is_skipped_not_fatal(tmp_path, spec, reason, capsys):
    if spec.get("credit", "x") is None:
        folder = tmp_path / "bad"
        folder.mkdir()
        (folder / "model.bam").write_bytes(b"")
        (folder / "avatar.json").write_text(json.dumps({"model": "model.bam"}))
    else:
        _drop_in(tmp_path, "bad", **spec)
    assert "bad" not in scene.all_avatars(tmp_path), reason
    assert "skipping model bad" in capsys.readouterr().out


def test_unreadable_json_is_skipped(tmp_path, capsys):
    folder = tmp_path / "broken"
    folder.mkdir()
    (folder / "avatar.json").write_text("{not json")
    assert "broken" not in scene.all_avatars(tmp_path)
    assert "unreadable" in capsys.readouterr().out


def test_drop_in_cannot_shadow_a_built_in(tmp_path, capsys):
    _drop_in(tmp_path, "jonny")
    reg = scene.all_avatars(tmp_path)
    assert reg["jonny"] is scene.AVATARS["jonny"]
    assert "name taken" in capsys.readouterr().out


@pytest.mark.parametrize("screen", [None, portal.Screen()], ids=["overlay", "portal"])
def test_swap_replaces_the_model_and_leaves_nothing_behind(base, registry, screen):
    sc = scene.AvatarScene(base, "jonny", portal=screen, registry=registry)
    first_actor = sc.actor
    lights_before = _lights_on_render(base)
    rooms_before = base.render.find_all_matches("**/mavis-room").get_num_paths()

    assert sc.next_avatar() == "twin"
    sc.swap("twin")

    assert sc.name == "twin"
    assert sc.credit.getText() == registry["twin"]["credit"]
    assert sc.actor is not first_actor and first_actor.is_empty()
    assert _lights_on_render(base) == lights_before, "lights stacked up"
    assert base.render.find_all_matches("**/mavis-room").get_num_paths() == rooms_before
    assert base.render.find_all_matches("**/mavis-pivot").get_num_paths() == (
        0 if screen is None else 1)
    sc.set_mouth(1.0)                       # the no-mouth driver: a no-op

    sc.swap("jonny")                        # and back round the cycle
    assert sc.name == "jonny" and len(sc.mouth_sliders) == 5
    assert sc.next_avatar() == "twin"
    sc._teardown()


def test_swap_keeps_him_hidden_while_asleep(base, registry):
    sc = scene.AvatarScene(base, "jonny", registry=registry)
    sc.hide()
    sc.swap("twin")
    assert sc.actor.is_hidden()
    sc._teardown()


def test_a_model_that_fails_to_load_puts_the_previous_one_back(base, registry, tmp_path):
    junk = tmp_path / "junk.bam"
    junk.write_bytes(b"not a model")
    reg = dict(registry, junk={"path": str(junk), "credit": "x",
                               "mouth": {"kind": "none"}})
    sc = scene.AvatarScene(base, "jonny", registry=reg)
    with pytest.raises(Exception):
        sc.swap("junk")
    assert sc.name == "jonny"
    assert not sc.actor.is_empty()
    assert sc.credit.getText() == scene.AVATARS["jonny"]["credit"]
    sc._teardown()


def test_next_avatar_is_none_with_a_single_model(base):
    reg = {"jonny": scene.AVATARS["jonny"]}
    sc = scene.AvatarScene(base, "jonny", registry=reg)
    assert sc.next_avatar() is None
    sc._teardown()


@pytest.fixture(scope="module")
def static_registry(base, tmp_path_factory):
    """A model with no skeleton at all -- what a mech head usually is."""
    path = tmp_path_factory.mktemp("static") / "box.bam"
    base.loader.load_model("models/box").write_bam_file(str(path))
    return {"jonny": scene.AVATARS["jonny"],
            "box": {"path": str(path), "credit": "Model: box (test)",
                    "mouth": {"kind": "none"}, "sway": 3.0}}


@pytest.mark.parametrize("screen", [None, portal.Screen()], ids=["overlay", "portal"])
def test_a_model_without_a_skeleton_loads_and_nods_when_he_talks(base, static_registry, screen):
    """It used to die on find('**/+Character').node() -- an empty NodePath."""
    sc = scene.AvatarScene(base, "box", portal=screen, registry=static_registry)
    assert sc._bundle is None and not sc.animated
    sc.set_mouth(1.0)
    assert sc.actor.get_p() == pytest.approx(3.0)
    sc.set_mouth(0.0)
    assert sc.actor.get_p() == pytest.approx(0.0)
    sc.idle(2.0)                            # sways, does not crash
    sc.swap("jonny")
    sc.swap("box")
    assert sc.name == "box"
    sc._teardown()


def test_head_fraction_frames_a_bust_on_more_of_the_model(base, static_registry):
    """A bust framed as a full figure zooms into the top of its helmet."""
    full = scene.AvatarScene(base, "box", registry=static_registry)
    full_head = full._measure_head()[3]
    full._teardown()
    bust_reg = dict(static_registry,
                    box=dict(static_registry["box"], head_fraction=0.5))
    bust = scene.AvatarScene(base, "box", registry=bust_reg)
    assert bust._measure_head()[3] == pytest.approx(full_head * 0.5 / scene.HEAD_FRACTION)
    bust._teardown()


def test_head_fraction_is_an_accepted_drop_in_key(tmp_path):
    _drop_in(tmp_path, "bust", head_fraction=0.5)
    assert scene.all_avatars(tmp_path)["bust"]["head_fraction"] == 0.5


def test_floor_is_out_of_sight_even_under_a_short_model(base, static_registry):
    """A bust's base is inside the window; a floor there filled the bottom
    third of the screen with a grey slab."""
    screen = portal.Screen()
    sc = scene.AvatarScene(base, "box", portal=screen, registry=static_registry)
    floor = sc.room.find("floor")
    floor_z = floor.get_z(base.render)
    eye_y = screen.nominal_eye[1]
    # Where the floor's far edge (at the back wall) crosses the glass, as
    # seen from the nominal eye: must be below the window's bottom edge.
    at_glass = floor_z * (-eye_y) / (sc.room_depth - eye_y)
    assert at_glass < -screen.height / 2
    sc._teardown()
