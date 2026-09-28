import math
import sys
import types

import pytest
from panda3d.core import loadPrcFileData

loadPrcFileData("", "window-type none\naudio-library-name null\n"
                    "hardware-animated-vertices false")

from direct.showbase.ShowBase import ShowBase  # noqa: E402
from panda3d.core import GeomVertexReader, Thread  # noqa: E402

from avatar import scene  # noqa: E402


@pytest.fixture(scope="module")
def base():
    b = ShowBase()
    yield b
    b.destroy()


@pytest.fixture(scope="module")
def avatar(base):
    """Always the committed CC-BY model.

    `keanu` is gitignored -- it is an extracted CD Projekt Red asset and this
    repo is public -- so it is absent on a fresh clone and cannot be what the
    suite asserts against. Pinning also stops these tests from silently
    changing meaning on a machine that happens to have built the other model.
    """
    return scene.AvatarScene(base, "jonny")


def _vertices(actor, mesh):
    node = [g for g in actor.findAllMatches("**/+GeomNode")
            if g.getName() == mesh][0].node()
    vd = node.getGeom(0).getVertexData().animateVertices(
        True, Thread.getCurrentThread())
    reader = GeomVertexReader(vd, "vertex")
    out = []
    while not reader.isAtEnd():
        out.append(tuple(reader.getData3()))
    return out


def test_actor_loads_with_full_skeleton(avatar):
    assert len(avatar.actor.getJoints()) >= 77


def test_mouth_sliders_are_found(avatar):
    """Sliders live in the PartBundle, not the scene graph -- a
    findAllMatches("**/+CharacterSlider") search returns zero and is the
    reason an earlier session wrongly concluded this model had no morphs."""
    assert len(avatar.mouth_sliders) == 5


def test_set_mouth_moves_head_geometry(avatar):
    avatar.set_mouth(0.0)
    closed = _vertices(avatar.actor, "Wolf3D_Head")
    avatar.set_mouth(1.0)
    opened = _vertices(avatar.actor, "Wolf3D_Head")

    moved = sum(1 for a, b in zip(closed, opened) if a != b)
    assert moved > 500


def test_no_mesh_escapes_the_model_bounds(avatar):
    """Guards the built .bam, not the repair tool's GLB output.

    The .bam is a gitignored artifact rebuilt by whatever panda3d-gltf is
    installed, and every other test here samples only Wolf3D_Head. All of them
    passed while Wolf3D_Outfit_Bottom was exploded to +/-18 units by a
    mis-strided read -- the only symptom was a human noticing a grey mass on
    screen. A whole-model sanity check catches that class headlessly.
    """
    low, high = avatar.actor.get_tight_bounds()
    height = high[2] - low[2]
    assert 1.0 < height < 3.0, f"model is {height:.2f} units tall, not human-scale"

    for node in avatar.actor.findAllMatches("**/+GeomNode"):
        lo, hi = node.get_tight_bounds(avatar.actor)
        assert hi[2] - lo[2] <= height + 1e-3, (
            f"{node.getName()} spans {hi[2] - lo[2]:.2f} units inside a "
            f"{height:.2f}-unit model"
        )


def test_set_mouth_clamps_negative_input(avatar):
    avatar.set_mouth(-5.0)
    assert avatar.mouth_sliders[0].getValue() == 0.0


def test_attribution_text_is_present(avatar):
    assert "Stuxed" in avatar.credit.getText()


def _at(sc, t, clip="idle"):
    """Put the scene on `clip` with its dwell clock started at time `t`.

    Also restores every clip's control effect. The `keanu` fixture is
    module-scoped, so a test that leaves a clip faded to zero silently
    freezes the model for every test after it -- which is exactly what
    blending makes possible.
    """
    sc._fade = None
    sc._pending = None
    sc._looping = None
    sc._oneshot = None
    sc._next_variety = None
    sc._clip_start = 0.0
    sc.idle(t)
    sc.play(clip)
    sc.idle(t)
    for other in sc.actor.get_anim_names():
        sc.actor.set_control_effect(other, 1.0 if other == clip else 0.0)
    return sc


def test_a_switch_inside_the_dwell_is_deferred_not_dropped(keanu):
    """Dropping it is how the pose ends up disagreeing with what he is doing."""
    _at(keanu, 0.0, "idle")

    keanu.play("smoking")
    assert keanu._pending is not None, "switch inside the dwell was not held"

    keanu.idle(1.0)
    assert keanu._fade is None, "switched away before MIN_DWELL elapsed"

    keanu.idle(scene.MIN_DWELL + 0.1)
    assert keanu._fade is not None and keanu._fade[1] == "smoking", (
        "deferred switch was dropped instead of applied once the dwell expired")


def test_asking_for_the_current_clip_cancels_a_deferred_switch(keanu):
    """"Stay here" must beat a request made a moment earlier."""
    _at(keanu, 0.0, "idle")
    keanu.play("smoking")
    assert keanu._pending is not None

    keanu.play("idle")

    assert keanu._pending is None, "he would have wandered off to smoking later"


def test_dismiss_ignores_the_dwell(keanu):
    """Being told to leave is not something to sit on for two seconds."""
    _at(keanu, 0.0, "idle")

    keanu.play("dismiss", loop=False)

    assert keanu._pending is None
    assert keanu._fade is None, "dismiss should snap, not fade"


def test_clips_cross_fade_rather_than_cut(keanu, monkeypatch):
    """`actor.loop()` restarts at frame 0; that cut is what read as a glitch.

    Asserts the weights this code actually sends. Panda3D's Actor has
    setControlEffect but no getter, so the call is recorded rather than
    read back.
    """
    _at(keanu, 0.0, "idle")
    keanu.idle(scene.MIN_DWELL + 0.1)

    sent = []
    real = keanu.actor.set_control_effect
    monkeypatch.setattr(keanu.actor, "set_control_effect",
                        lambda clip, w: (sent.append((clip, w)), real(clip, w))[1])

    keanu.play("smoking")
    start = keanu._fade[2]
    sent.clear()
    keanu.idle(start + scene.CROSSFADE * 0.5)

    weights = dict(sent)
    assert 0.0 < weights["smoking"] < 1.0, f"mid-fade weight not partial: {weights}"
    assert weights["idle"] == pytest.approx(1.0 - weights["smoking"]), (
        "the two clips must sum to one or he gets heavier and lighter mid-blend")

    sent.clear()
    keanu.idle(start + scene.CROSSFADE + 0.01)
    assert keanu._fade is None
    assert dict(sent)["smoking"] == 1.0


def test_cigarette_stays_seated_between_the_fingers(keanu):
    """The prop offset must be fitted against the ANIMATED clip.

    The original numbers were measured on the bind pose, and the fingers
    animate out from under them: at frame 0 the cigarette was entirely inside
    the hand and invisible, and by frame 30 it speared through the index and
    middle fingers. Nothing in the suite noticed, because a prop's position is
    not something any other assertion looks at.

    The ideal anchor -- the midpoint of the index and middle DISTAL joints,
    pushed clear of the skin and set back along the fingers -- is constant in
    the anchor joint's local space across all 538 frames, so this can be
    pinned exactly rather than sampled loosely.
    """
    from panda3d.core import NodePath

    actor = keanu.actor
    assert keanu.prop is not None, "no cigarette attached"
    idx = actor.expose_joint(None, "modelRoot", "ValveBiped.Bip01_R_Finger12")
    mid = actor.expose_joint(None, "modelRoot", "ValveBiped.Bip01_R_Finger22")
    idx_base = actor.expose_joint(None, "modelRoot", "ValveBiped.Bip01_R_Finger11")
    render = keanu.base.render

    for frame in (0, 130, 260, 400, 530):
        actor.pose("smoking", frame)
        actor.update(force=True)

        finger_dir = idx.get_pos(render) - idx_base.get_pos(render)
        finger_dir.normalize()
        target = (idx.get_pos(render) + mid.get_pos(render)) * 0.5 - finger_dir * 0.022
        drift = (keanu.prop.get_pos(render) - target).length()

        assert drift < 0.02, (
            f"frame {frame}: cigarette is {drift*1000:.0f}mm from the grip "
            "between the fingers -- it is buried in the hand or floating free")


def test_caption_shows_the_exact_answer_text(avatar):
    avatar.show_caption("gold is a hedge, choom")

    assert avatar._caption.getText() == "gold is a hedge, choom"

    avatar.show_caption("")
    assert avatar._caption.getText() == ""


def test_caption_never_covers_the_credit(avatar):
    """The credit is an attribution condition -- a caption may not cover it.

    Asserting the ANCHOR is above the credit proves nothing: the caption grows
    downward, so only the last rendered row matters. wordwrap breaks on
    whitespace only, so hyphenated terms pack into many more rows than prose
    of the same length -- and MAVIS_MAX_ANSWER_CHARS can raise the cap to 420.
    That worst case is what this pins.
    """
    worst = " ".join(["tier-pool-drawdown-breaker-latency"] * 20)[:420]
    avatar.show_caption(worst)

    caption_bottom = avatar._caption.getTightBounds()[0][2]
    credit_top = avatar.credit.getTightBounds()[1][2]

    assert caption_bottom > credit_top, (
        f"caption reaches {caption_bottom:.3f}, credit top is {credit_top:.3f}")


def test_caption_hides_with_the_actor(avatar):
    """The window is transparent: an orphaned caption would float over the
    bare desktop after he is dismissed, exactly like the notice."""
    avatar.show_caption("still here")
    avatar.hide()

    assert avatar._caption.isHidden()

    avatar.show()
    assert not avatar._caption.isHidden()


def test_every_avatar_declares_a_credit():
    """Attribution is a licence condition for the CC-BY model and basic
    honesty for the ported one, so no entry may ship without a credit."""
    for name, config in scene.AVATARS.items():
        assert config["credit"].strip(), f"{name} has no credit string"
        assert config["mouth"]["kind"] in scene._DRIVERS


def test_camera_is_taken_off_the_mouse_when_there_is_a_window():
    """ShowBase's default Trackball2D writes its own transform onto
    base.camera every frame. Framing works by moving the actor and leaving the
    camera at the origin, so the first mouse drag in the window replaced the
    framed view with the trackball's pose and the avatar left the frame --
    indistinguishable from a crash. The suite runs `window-type none`, so the
    two branches are exercised against a stub rather than a real window."""
    calls = []
    windowed = types.SimpleNamespace(
        base=types.SimpleNamespace(win=object(),
                                   disableMouse=lambda: calls.append("called")))
    scene.AvatarScene._release_camera(windowed)
    assert calls == ["called"], "camera left under the mouse trackball"

    headless = types.SimpleNamespace(
        base=types.SimpleNamespace(win=None, disableMouse=lambda: calls.append("bad")))
    scene.AvatarScene._release_camera(headless)
    assert calls == ["called"], "windowless base has no mouse to detach"


def test_head_stays_inside_the_frame():
    """HEAD_RISE biases the aim down the body to spend the frame on torso
    rather than empty air above his hair. At 0.5 the head's centre sits on the
    top edge, so anything at or past that has framed him out of his own shot."""
    assert 0.0 <= scene.HEAD_RISE < 0.5, scene.HEAD_RISE


def test_pbr_shader_initialises_once_per_window(base, monkeypatch):
    """simplepbr claims the display region via a FilterManager, so a second
    init dies with "Could not find appropriate DisplayRegion to filter" -- a
    second AvatarScene on one window (swapping models at runtime) crashed
    outright until the pipeline was cached on the ShowBase.

    Driven with a stub because the suite runs window-type none, where the
    real path is skipped entirely and the bug is invisible.
    """
    calls = []
    stub = types.ModuleType("simplepbr")
    stub.init = lambda **kwargs: calls.append(kwargs) or "pipeline"
    monkeypatch.setitem(sys.modules, "simplepbr", stub)
    monkeypatch.setattr(base, "win", object(), raising=False)
    monkeypatch.setattr(base, "_mavis_pbr_pipeline", None, raising=False)

    first = scene.AvatarScene(base, "jonny")
    second = scene.AvatarScene(base, "jonny")

    assert len(calls) == 1, f"simplepbr.init called {len(calls)} times"
    assert first.pipeline is second.pipeline


def test_idle_degrades_on_a_model_without_those_joints(avatar):
    """The idle channels name CDPR/Valve bones. jonny is a Ready Player Me
    skeleton that shares none of them, and it is the only model the suite can
    load -- so absent joints must be skipped silently, not raise."""
    assert avatar.motion.driven == []
    avatar.idle(0.0)
    avatar.idle(3.7)


def test_idle_layers_more_than_one_frequency():
    """A single sine reads as a metronome no matter how it is tuned. The head
    yaw carries two components (11.3s and 4.7s), so sampling exactly one short
    period apart must NOT return to the same value -- that difference is the
    whole reason the motion does not look looped."""
    yaw = [c for c in scene._KEANU_IDLE
           if c[0].endswith("Head1") and c[1] == "r"]
    assert len(yaw) > 1, "head yaw needs layered components"

    def total(t):
        return sum(deg * math.sin(2 * math.pi * (t / period + phase))
                   for _, _, deg, period, phase in yaw)

    shortest = min(c[3] for c in yaw)
    assert abs(total(1.0) - total(1.0 + shortest)) > 0.2


def test_idle_periods_are_non_harmonic():
    """Channels whose periods share a small common multiple re-align into a
    visible loop. Guards against someone 'tidying' these to round numbers."""
    periods = sorted({c[3] for c in scene._KEANU_IDLE})
    for i, a in enumerate(periods):
        for b in periods[i + 1:]:
            ratio = b / a
            assert abs(ratio - round(ratio)) > 0.05, (
                f"periods {a} and {b} are near-harmonic (ratio {ratio:.2f})"
            )


def test_explicit_unknown_avatar_is_rejected(monkeypatch):
    monkeypatch.setenv("MAVIS_AVATAR", "nobody")
    with pytest.raises(ValueError):
        scene.choose_avatar()


# --- the ported model: only runs where it has actually been built ----------

_KEANU = scene.ASSET_DIR / scene.AVATARS["keanu"]["bam"]
needs_keanu = pytest.mark.skipif(
    not _KEANU.exists(),
    reason="keanu.bam is gitignored (extracted CDPR asset); build it locally",
)


@pytest.fixture(scope="module")
def keanu(base):
    return scene.AvatarScene(base, "keanu")


@needs_keanu
def test_keanu_uses_the_jaw_joint_not_morphs(keanu):
    """This model has no morph targets at all -- Cyberpunk animates faces with
    joints, which is exactly why its facial rig survived extraction."""
    assert isinstance(keanu.mouth, scene._JawMouth)
    assert keanu.mouth_sliders == []


@needs_keanu
def test_keanu_jaw_moves_head_and_teeth(keanu):
    """Rotating a controlled joint does nothing visible without a bundle
    forceUpdate(); this fails flat if that call is ever dropped."""
    keanu.set_mouth(0.0)
    shut_head = _vertices(keanu.actor, "head")
    shut_teeth = _vertices(keanu.actor, "teeth")

    keanu.set_mouth(1.0)
    open_head = _vertices(keanu.actor, "head")
    open_teeth = _vertices(keanu.actor, "teeth")

    assert sum(1 for a, b in zip(shut_head, open_head) if a != b) > 500
    assert sum(1 for a, b in zip(shut_teeth, open_teeth) if a != b) > 100


@needs_keanu
def test_keanu_head_is_framed_in_actor_space(keanu):
    """get_tight_bounds() with no reference reports the mesh's own untrans-
    formed space. This model carries a scale above its meshes, so reading it
    that way is out by ~40x and frames empty air."""
    head = keanu.actor.find("**/head")
    low, high = head.get_tight_bounds(keanu.actor)
    assert 1.0 < low[2] < 2.0, f"head sits at z {low[2]:.2f}, not on a 1.8m body"


@needs_keanu
def test_keanu_uses_clips_rather_than_procedural_idle(keanu):
    """Retargeted clips drive the body, and the procedural channels stand down.

    They cannot both run: `_IdleMotion` takes joints with controlJoint, which
    detaches a joint from animation entirely, and those are the same head, neck
    and clavicle joints a clip animates. The clip wins because it already
    carries breathing, weight shift and head movement.
    """
    assert keanu.animated is True
    assert keanu.motion.driven == [], "procedural channels must not take joints"
    assert set(scene.AVATARS["keanu"]["anims"]) <= set(keanu.actor.getAnimNames())


@needs_keanu
def test_keanu_animation_moves_the_body(keanu):
    """The model ships with no animation of its own -- a game rip is a mesh in
    its bind pose. These frames exist only because tools/retarget_anim.py put
    them there, so this is what proves the retarget survived export."""
    bundle = keanu._bundle
    keanu.actor.set_control_effect("idle", 1.0)   # blending scales pose() too
    keanu.actor.pose("idle", 0)
    bundle.forceUpdate()
    first = _vertices(keanu.actor, "head")

    keanu.actor.pose("idle", 120)
    bundle.forceUpdate()
    later = _vertices(keanu.actor, "head")

    assert sum(1 for a, b in zip(first, later) if a != b) > 500


@needs_keanu
def test_keanu_can_switch_clips_and_reports_unknown_ones(keanu):
    assert keanu.play("smoking") is True
    assert keanu.play("idle") is True
    assert keanu.play("moonwalk") is False


@needs_keanu
def test_keanu_jaw_still_free_while_a_clip_plays(keanu):
    """No retargeted clip touches mid_J_jaw_JNT -- it is a CDPR facial joint and
    Mixamo has no opinion about faces. If a clip ever did animate it, lipsync
    and the animation would fight over the same joint."""
    keanu.actor.loop("idle")
    keanu.set_mouth(0.0)
    shut = _vertices(keanu.actor, "teeth")
    keanu.set_mouth(1.0)
    opened = _vertices(keanu.actor, "teeth")
    assert sum(1 for a, b in zip(shut, opened) if a != b) > 100


@needs_keanu
def test_keanu_breathing_drives_both_shoulders_together(keanu):
    """Breathing is only legible if the shoulders move as a pair and on one
    cycle; mismatched phase reads as a shrug."""
    breath = [c for c in scene._KEANU_IDLE if "Clavicle" in c[0]]
    assert len(breath) == 2
    left, right = sorted(breath)
    assert left[1:] == right[1:], "clavicles must share axis, travel and phase"


def _variety_due(sc, t):
    """Rest on idle past its dwell with a variety break scheduled for `t`."""
    _at(sc, 0.0, "idle")
    sc._next_variety = t
    sc.idle(t)


@needs_keanu
def test_idle_breaks_into_a_variety_clip_once_it_is_due(keanu):
    _variety_due(keanu, 20.0)
    assert keanu._fade is not None, "the idle never broke into variety"
    outgoing, incoming, _start, loop = keanu._fade
    assert (outgoing, loop) == ("idle", False)
    assert incoming in scene.AVATARS["keanu"]["idle_variety"]


@needs_keanu
def test_variety_does_not_repeat_the_same_clip_back_to_back(keanu):
    seen = []
    for _ in range(4):
        _variety_due(keanu, 20.0)
        seen.append(keanu._fade[1])
    assert all(a != b for a, b in zip(seen, seen[1:])), seen


@needs_keanu
def test_a_variety_clip_fades_home_before_its_last_frame(keanu):
    _variety_due(keanu, 20.0)
    clip = keanu._fade[1]
    keanu.idle(20.0 + scene.CROSSFADE + 0.01)      # fade in completes
    assert keanu._oneshot == clip

    control = keanu.actor.getAnimControl(clip)
    # Still PLAYING, within CROSSFADE of the end. pose() would stop it, and
    # the not-playing fallback would pass this test for the wrong reason.
    keanu.actor.play(clip, fromFrame=control.getNumFrames() - 3)
    assert control.isPlaying()
    keanu.idle(21.0)
    assert keanu._fade is not None and keanu._fade[:2] == (clip, "idle"), (
        "he would freeze on the variety clip's last frame")
    for other in keanu.actor.get_anim_names():
        keanu.actor.set_control_effect(other, 1.0 if other == "idle" else 0.0)


@needs_keanu
def test_a_state_change_during_variety_fades_rather_than_snaps(keanu):
    _variety_due(keanu, 20.0)
    clip = keanu._fade[1]
    keanu.idle(20.0 + scene.CROSSFADE + 0.01)
    keanu.play("smoking")
    assert keanu._fade is not None and keanu._fade[:2] == (clip, "smoking")


@needs_keanu
def test_variety_never_interrupts_a_conversational_pose(keanu):
    _at(keanu, 0.0, "smoking")
    keanu._next_variety = 1.0
    keanu.idle(60.0)
    assert keanu._fade is None and keanu._looping == "smoking"


@needs_keanu
def test_dismiss_is_never_sent_home_to_idle(keanu):
    _at(keanu, 0.0, "idle")
    keanu.play("dismiss", loop=False)
    keanu.actor.pose("dismiss", keanu.actor.getAnimControl("dismiss").getNumFrames() - 1)
    keanu.idle(30.0)
    assert keanu._fade is None and keanu._oneshot == "dismiss"
