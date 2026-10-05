"""Portal mode in the scene: he stands behind the glass, inside his room."""
import pytest
from panda3d.core import loadPrcFileData

loadPrcFileData("", "window-type none\naudio-library-name null\n"
                    "hardware-animated-vertices false")

from direct.showbase.ShowBase import ShowBase  # noqa: E402

from avatar import portal, scene  # noqa: E402

SCREEN = portal.Screen(width=0.302, height=0.196)


@pytest.fixture(scope="module")
def base():
    b = ShowBase()
    yield b
    b.destroy()


@pytest.fixture(scope="module")
def avatar(base):
    """The mech with its own portal framing STRIPPED, so these tests pin the
    default framing logic rather than one model's tuning (the mech's tight
    close-up deliberately crops its crest, as the reel does)."""
    reg = scene.all_avatars()
    plain = {k: v for k, v in reg["mech-bust"].items()
             if k not in ("portal_framing", "portal_rise")}
    return scene.AvatarScene(base, "mech-bust", portal=SCREEN,
                             registry=dict(reg, **{"mech-bust": plain}))


def _head_bounds(avatar):
    head = avatar.actor.find(f"**/{avatar.config['head_mesh']}")
    return head.get_tight_bounds(avatar.base.render)


def test_head_is_behind_the_glass_and_centred(avatar):
    low, high = _head_bounds(avatar)
    centre_x = (low[0] + high[0]) / 2
    centre_y = (low[1] + high[1]) / 2
    assert low[1] > 0.0, "part of his head pokes out through the screen"
    assert centre_y == pytest.approx(scene.PORTAL_DEPTH, abs=0.01)
    assert centre_x == pytest.approx(0.0, abs=0.01)


def test_he_fits_inside_his_room(avatar):
    """The first room was screen-sized and its ceiling cut through his head."""
    room_low, room_high = avatar.room.get_tight_bounds(avatar.base.render)
    low, high = avatar.actor.get_tight_bounds(avatar.base.render)
    assert high[2] < room_high[2], "his head is above the ceiling"
    assert low[2] >= room_low[2] - 1e-3, "his feet are through the floor"
    assert high[1] < room_high[1], "he is through the back wall"


def test_head_is_visible_through_the_window_from_the_nominal_eye(avatar):
    """Framed like the overlay: the whole head inside the glass, from centre."""
    low, high = _head_bounds(avatar)
    eye_y = SCREEN.nominal_eye[1]
    for z in (low[2], high[2]):
        for y in (low[1], high[1]):
            # Where the ray from the eye to this point crosses the glass.
            at_glass = z * (-eye_y) / (y - eye_y)
            assert abs(at_glass) <= SCREEN.height / 2 + 1e-6


def test_overlay_mode_is_untouched(base):
    """No portal: no room, no pivot, actor parented straight to render."""
    overlay = scene.AvatarScene(base, "mech-bust")
    assert overlay.room is None and overlay.pivot is None
    assert overlay.actor.get_parent() == base.render
    overlay.look_from((0.2, -0.6, 0.0))     # a no-op, not an error
    assert overlay.gaze == 0.0
    overlay.actor.cleanup()
    overlay.actor.remove_node()


def test_gaze_turns_his_head_toward_the_viewer_gradually(avatar):
    avatar.pivot.set_h(0)
    avatar.look_from((0.25, -0.6, 0.0))
    assert avatar.gaze > 0
    avatar.idle(1.0)
    first = avatar.pivot.get_h()
    assert 0 < first < avatar.gaze, "should ease, not snap"
    for i in range(200):
        avatar.idle(1.0 + i / 60)
    assert avatar.pivot.get_h() == pytest.approx(avatar.gaze, abs=0.05)


def test_every_wall_faces_into_the_room(avatar):
    """The first build had both side walls facing OUT: backface-culled, they
    simply were not there, and leaning showed grey void instead of a wall."""
    render = avatar.base.render
    low, high = avatar.room.get_tight_bounds(render)
    centre = (low + high) / 2
    for name in ("back", "left", "right", "ceiling", "floor"):
        card = avatar.room.find(name)
        assert not card.is_empty(), name
        # CardMaker cards face their local -y.
        normal = render.get_relative_vector(card, (0, -1, 0))
        to_centre = centre - card.get_pos(render)
        assert normal.dot(to_centre) > 0, f"{name} wall faces out of the room"


def test_film_finish_sits_over_the_scene_but_under_the_text(avatar):
    """Vignette and grain must never dim the captions or the credit."""
    assert avatar.film is not None
    assert avatar.film.root.get_bin_name() == "background"
    assert avatar.film.root.get_parent() == avatar.base.render2d
    from panda3d.core import TextureStage
    stage_ = TextureStage.get_default()
    before = avatar.film.grain.get_tex_offset(stage_)
    avatar.film.step()
    assert avatar.film.grain.get_tex_offset(stage_) != before, "grain must move"


def test_hud_is_pinned_to_the_top_left_of_the_glass(avatar):
    avatar.show_hud("JOHNNY // LOCKED")
    assert avatar._hud.getText() == "JOHNNY // LOCKED"
    assert avatar._hud.get_parent() == avatar.base.a2dTopLeft


def test_a_model_without_a_clip_breathes_and_an_animated_one_does_not(base):
    import math
    from avatar import portal
    path = str(scene.EXTRA_DIR / "mech-bust" / "mech_bust.glb")
    reg = {"still": {"path": path, "credit": "x", "mouth": {"kind": "none"},
                     "head_mesh": "mech_mech_head_mat_0"},
           "mech-bust": scene.all_avatars()["mech-bust"]}
    sc = scene.AvatarScene(base, "still", portal=portal.Screen(), registry=reg)
    assert not sc.animated
    zs = []
    for i in range(int(scene.BREATH_PERIOD * 30)):
        sc.idle(i / 30)
        zs.append(sc.pivot.get_z())
    assert max(zs) - min(zs) == pytest.approx(2 * sc._breath, rel=0.05)
    sc.swap("mech-bust")
    assert sc.animated
    z0 = sc.pivot.get_z()
    for i in range(60):
        sc.idle(10 + i / 30)
    assert sc.pivot.get_z() == pytest.approx(z0)
    sc._teardown()


def test_no_side_wall_or_ceiling_is_in_view_from_straight_on(avatar):
    """Sat square-on you see only the backdrop, as in the reel; the walls
    appear only as you lean. Sized to his depth instead, the room showed its
    walls from dead centre and read as a diorama box."""
    eye_d = -SCREEN.nominal_eye[1]
    low, high = avatar.room.get_tight_bounds(avatar.base.render)
    back = avatar.room_depth
    # Where the window's edges project onto the back wall from the nominal eye.
    reach_x = SCREEN.width / 2 * (eye_d + back) / eye_d
    reach_z = SCREEN.height / 2 * (eye_d + back) / eye_d
    assert high[0] >= reach_x - 1e-4 and -low[0] >= reach_x - 1e-4
    assert high[2] >= reach_z - 1e-4
