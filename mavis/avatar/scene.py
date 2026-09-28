"""The Panda3D side of the avatar: window, model, idle motion, mouth.

Two different models are supported because they move their mouths in
completely different ways, and because only one of them may be committed.

* **jonny** -- the Stuxed Sketchfab model, CC BY, in the repo. A Ready Player
  Me export, so the mouth is a `mouthOpen` *morph target*.
* **keanu** -- the KonnieGFX port of CD Projekt Red's actual character. Far
  better likeness, but it is an extracted game asset and this repository is
  public, so it is gitignored and exists only on machines that build it. It
  carries no morph targets at all; Cyberpunk animates faces with *joints*,
  which is why its facial rig survived extraction. The mouth is a rotation of
  `mid_J_jaw_JNT`.

The test suite can therefore only ever run against `jonny`, which is why both
mechanisms stay supported rather than the better model simply replacing the
other. Tests pin their model explicitly; nothing should rely on the default.

Whichever mechanism is used, the mouth only moves if the character's
`PartBundle` is told to `forceUpdate()`. Neither writing a slider nor rotating
a controlled joint updates the vertices on its own -- both look like a silent
no-op without it, and both wasted a debugging session that way.
"""
import math
import os
import random
from pathlib import Path

from direct.actor.Actor import Actor
from direct.gui.OnscreenText import OnscreenText
from panda3d.core import AmbientLight, DirectionalLight, TextNode, Vec4

CAPTION_TOP = -0.42
# Last row may not reach the credit band below it.
CAPTION_FLOOR = -0.88

from avatar import props

ASSET_DIR = Path(__file__).resolve().parent.parent / "assets" / "avatar"

# Idle motion, as (joint, axis, degrees, seconds, phase) channels summed per
# joint+axis. On this rig h tilts, p nods and r turns -- established by posing
# each axis and looking, not from the bone names.
#
# Periods are deliberately non-harmonic (11.3 / 7.9 / 13.1 / 17.9 ...) so the
# layers never re-align into a visible loop. A single sine, however well tuned,
# reads as a metronome; several that never agree read as a person who cannot
# quite keep still. Amplitudes are small on purpose -- this is someone standing
# there, not someone performing.
#
# No blink channel, though the rig carries 70 eyelid joints: he wears opaque
# aviators and the eyes are not visible at all. Blinking is usually the best
# value per unit effort on a face; here it would be invisible work.
_KEANU_IDLE = (
    ("ValveBiped.Bip01_Head1", "r", 3.4, 11.3, 0.00),
    ("ValveBiped.Bip01_Head1", "r", 1.1, 4.70, 0.37),
    ("ValveBiped.Bip01_Head1", "p", 1.5, 7.90, 0.21),
    ("ValveBiped.Bip01_Head1", "h", 1.7, 13.10, 0.63),
    ("ValveBiped.Bip01_Neck1", "r", 1.2, 17.90, 0.11),
    ("ValveBiped.Bip01_Neck1", "p", 0.8, 9.70, 0.48),
    # Breathing: shoulders and upper chest share one 4.1s cycle.
    ("ValveBiped.Bip01_L_Clavicle", "p", 1.1, 4.10, 0.00),
    ("ValveBiped.Bip01_R_Clavicle", "p", 1.1, 4.10, 0.00),
    ("ValveBiped.Bip01_Spine4", "p", 0.5, 4.10, 0.00),
)

AVATARS = {
    "keanu": {
        "bam": "keanu.bam",
        "head_mesh": "head",
        # Real retargeted clips, built by tools/retarget_anim.py. When these are
        # present they drive the body and the procedural channels below are not
        # used at all -- a clip already carries breathing, weight shift and
        # head movement, and it cannot share joints with controlJoint, which
        # detaches a joint from animation entirely.
        "anims": ("idle", "smoking", "dismiss", "angry", "stance"),
        "idle_anim": "idle",
        # Mixed into the idle now and then (see VARIETY_EVERY): Mixamo's
        # "Offensive Idle" and "Angry". Each plays once, then he settles back.
        "idle_variety": ("stance", "angry"),
        # Which clip each conversational moment plays; read by avatar.states.
        # He lights up while he digs for an answer or waits on you, and waves
        # you off on the way out. A moment left out plays nothing new.
        "poses": {
            "listening": "idle",
            "prompting": "smoking",
            "thinking": "smoking",
            "speaking": "idle",
            "dismissing": "dismiss",
        },
        # Kept as the fallback for a model built without animation.
        "idle": _KEANU_IDLE,
        # The whole-actor yaw rotates about an axis through the head, so it
        # swings the shoulders while the head stays put -- backwards. Kept only
        # as a trace of weight shift now that real joints carry the motion.
        "sway": 2.0,
        # ASCII only: Panda3D's default font has no glyph for the likes of
        # U+00B7 or U+00A9 and draws them as empty boxes.
        "credit": "Model: Johnny Silverhand port by KonnieGFX - "
                  "character (c) CD Projekt Red",
        "mouth": {"kind": "joint", "joint": "mid_J_jaw_JNT",
                  "axis": "r", "degrees": 14.0},
        # He smokes with the chrome hand, so the cigarette hangs off the left
        # index finger, and exists only while a clip that holds one plays.
        # Offsets are metres in the joint's own frame, found by rendering.
        # The RIGHT (flesh) hand: it is the one the smoking clip raises, its
        # index tip coming 175mm from the jaw joint at frame 114 against the
        # chrome hand's 194mm at 196. Fitted, not guessed -- the filter end
        # sits 25mm behind the pinch of the index and middle fingers, running
        # along the index so the lit end clears the fingertips.
        # FITTED AGAINST THE ANIMATED CLIP, not the bind pose -- that is the
        # whole point. The previous offset was measured on the rest pose and
        # the fingers animate out from under it: at frame 0 the cigarette was
        # entirely inside the hand (invisible) and by frame 30 it speared
        # through the index and middle fingers. Measured over 538 frames, the
        # midpoint of the index and middle DISTAL joints pushed 12mm clear of
        # the skin is constant in this joint's local space to 4 decimal places,
        # so a static offset is correct -- the old numbers were just wrong,
        # with z the right magnitude and the wrong sign.
        "prop": {"joint": "ValveBiped.Bip01_R_Finger11",
                 "pos": (0.01020, -0.01338, 0.00348), "hpr": (152.5, 90.0, -61.7),
                 "clips": ("smoking",)},
    },
    "jonny": {
        "bam": "jonny_fixed.bam",
        "head_mesh": "Wolf3D_Head",
        # A Ready Player Me skeleton: none of the joints above exist on it, so
        # it degrades to the whole-actor sway and nothing is driven per-joint.
        "idle": (),
        "sway": 12.0,
        "credit": 'Model: "Jonny Silverhand" by Stuxed (CC BY)',
        "mouth": {"kind": "slider", "slider": "mouthOpen", "gain": 1.0},
    },
}

# Best-looking first. `MAVIS_AVATAR` overrides; tests pass a name directly.
PREFERENCE = ("keanu", "jonny")

HEAD_FRACTION = 0.19
# How much of the view the head spans: the framed height is this many head
# heights. A head-and-shoulders crop was 2.6; this is a torso portrait that
# ends at the belt. Chosen by rendering candidates and looking -- past ~4 the
# legs come into frame.
#
# Beware judging this from a downscaled screenshot: the chrome arm's thin
# high-contrast detail aliases to a white smear when the image is resampled,
# which looks like a blown-out material and is not one. Measured in the
# rendered pixels, no arm pixel exceeds 0.85 luminance at any framing.
FRAMING = 3.05
# The framing is measured about the head, so widening it alone would keep the
# head dead centre and spend half the new height on empty air above his hair.
# Bias the actor up by this fraction of the framed height to spend it downward
# on the torso instead. 0.5 would put the head's centre at the very top edge.
HEAD_RISE = 0.31
DEFAULT_FOV = 30.0


def choose_avatar() -> str:
    """Name of the avatar to load: env override, else the best one built."""
    requested = os.environ.get("MAVIS_AVATAR")
    if requested:
        if requested not in AVATARS:
            raise ValueError(
                f"MAVIS_AVATAR={requested!r} is not one of {sorted(AVATARS)}"
            )
        return requested
    for name in PREFERENCE:
        if (ASSET_DIR / AVATARS[name]["bam"]).exists():
            return name
    return PREFERENCE[-1]


def load_actor(loader, name: str) -> Actor:
    path = ASSET_DIR / AVATARS[name]["bam"]
    if not path.exists():
        raise FileNotFoundError(
            f"avatar model {name!r} missing at {path} -- see "
            "assets/avatar/ATTRIBUTION.md for how to rebuild it"
        )
    return Actor(str(path))


def _collect_sliders(part, name, acc):
    if type(part).__name__ == "CharacterSlider" and part.getName() == name:
        acc.append(part)
    for i in range(part.getNumChildren()):
        _collect_sliders(part.getChild(i), name, acc)
    return acc


class _SliderMouth:
    """Morph-target mouth. Sliders live in the PartBundle, NOT the scene graph
    -- `findAllMatches("**/+CharacterSlider")` returns zero and once led a
    session to conclude the model had no morphs at all."""

    def __init__(self, actor, bundle, config):
        self._bundle = bundle
        self._gain = config.get("gain", 1.0)
        self.sliders = _collect_sliders(bundle, config["slider"], [])
        if not self.sliders:
            raise ValueError(f"no {config['slider']!r} sliders in this model")

    def set(self, amount: float) -> None:
        value = max(0.0, min(1.0, amount)) * self._gain
        for slider in self.sliders:
            slider.applyFreezeScalar(value)
        self._bundle.forceUpdate()


class _JawMouth:
    """Joint-driven mouth: rotate the jaw away from its rest pose.

    The axis and travel are per-model and were found by rendering the jaw at
    each of h/p/r and looking -- on this rig `r` opens the mouth and the other
    two skew the face sideways.
    """

    def __init__(self, actor, bundle, config):
        self._bundle = bundle
        self._joint = actor.controlJoint(None, "modelRoot", config["joint"])
        if self._joint is None or self._joint.isEmpty():
            raise ValueError(f"joint {config['joint']!r} not found in this model")
        self._axis = config["axis"]
        self._degrees = config["degrees"]
        self._rest = {"h": self._joint.getH(),
                      "p": self._joint.getP(),
                      "r": self._joint.getR()}[self._axis]
        self._apply = {"h": self._joint.setH,
                       "p": self._joint.setP,
                       "r": self._joint.setR}[self._axis]
        self.sliders = []

    def set(self, amount: float) -> None:
        value = max(0.0, min(1.0, amount))
        self._apply(self._rest + value * self._degrees)
        self._bundle.forceUpdate()


_DRIVERS = {"slider": _SliderMouth, "joint": _JawMouth}

SWAY_RATE = 0.4

# Clips cross-fade rather than cut. `actor.loop()` restarts at frame 0, which
# is what made pose changes read as a glitch rather than a movement.
CROSSFADE = 0.45
# ...and once a clip starts it holds for this long before giving way, because
# the moment table sends him to `smoking` for "thinking" and back to `idle`
# for "speaking": a short think would otherwise flash the cigarette up and
# snap it away again inside a second.
MIN_DWELL = 2.5
# Being told to leave is not something to sit on.
URGENT = frozenset({"dismiss"})
# While he rests on his idle clip, every so often he breaks out of it into one
# of the model's `idle_variety` clips, plays it through once and settles back.
# Seconds of plain idle between two of those, drawn fresh each time so it
# never becomes a metronome.
VARIETY_EVERY = (15.0, 35.0)


def _smoothstep(t: float) -> float:
    """3t^2 - 2t^3, clamped. Linear weights make the swap visible at the ends."""
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    return t * t * (3.0 - 2.0 * t)


class _IdleMotion:
    """Layered sine motion on real joints, so the body is never quite still.

    Channels are summed per joint+axis against the joint's rest pose, which is
    sampled once at construction -- so this composes with whatever pose the
    model loads in rather than snapping it to zero.

    Joints named in the config but absent from the model are skipped, not an
    error: the same code has to run against a Ready Player Me skeleton that
    shares none of these bone names.
    """

    _SETTER = {"h": "setH", "p": "setP", "r": "setR"}
    _INDEX = {"h": 0, "p": 1, "r": 2}

    def __init__(self, actor, bundle, channels):
        self._bundle = bundle
        self._targets = {}
        controlled = {}

        for name, axis, degrees, period, phase in channels:
            if name not in controlled:
                node = actor.controlJoint(None, "modelRoot", name)
                controlled[name] = (
                    node if node is not None and not node.isEmpty() else None
                )
            node = controlled[name]
            if node is None:
                continue

            key = (name, axis)
            if key not in self._targets:
                rest = node.getHpr()[self._INDEX[axis]]
                self._targets[key] = (getattr(node, self._SETTER[axis]), rest, [])
            self._targets[key][2].append((degrees, period, phase))

        self.driven = sorted({name for name, _ in self._targets})

    def apply(self, elapsed: float) -> None:
        if not self._targets:
            return
        for setter, rest, waves in self._targets.values():
            value = rest
            for degrees, period, phase in waves:
                value += degrees * math.sin(2.0 * math.pi * (elapsed / period + phase))
            setter(value)
        self._bundle.forceUpdate()


class AvatarScene:
    """Owns the avatar's visual state. Knows nothing about audio."""

    def __init__(self, show_base, avatar: str = None):
        self.base = show_base
        self.name = avatar or choose_avatar()
        self.config = AVATARS[self.name]

        self._init_shader()
        self.actor = load_actor(show_base.loader, self.name)
        self.actor.reparent_to(show_base.render)

        character = self.actor.find("**/+Character").node()
        self._character = character
        self._bundle = character.getBundle(0)

        self.mouth = _DRIVERS[self.config["mouth"]["kind"]](
            self.actor, self._bundle, self.config["mouth"]
        )
        self.mouth_sliders = self.mouth.sliders

        # The mouth takes controlJoint on the jaw BEFORE any clip starts. The
        # jaw is a CDPR facial joint and no retargeted clip touches it, so the
        # two never contend -- but the ordering keeps it that way if one ever
        # does.
        # Keyed on the idle clip alone, not on every listed clip: a model built
        # without an optional clip (say, dismiss) should lose that one pose,
        # not all animation. play() checks each clip as it is asked for.
        idle_anim = self.config.get("idle_anim")
        self.animated = bool(idle_anim) and idle_anim in self.actor.getAnimNames()
        self._looping = None
        self.motion = _IdleMotion(
            self.actor, self._bundle,
            () if self.animated else self.config.get("idle", ())
        )
        if self.animated:
            # Pose to the clip's first frame BEFORE framing. loop() only starts
            # playback -- the pose is not applied until a frame is drawn, so
            # framing here would otherwise measure the bind pose and then
            # display him animated, leaving him sitting off-centre.
            self.actor.pose(self.config["idle_anim"], 0)
            self._bundle.forceUpdate()

        self.prop = self._attach_prop()

        self._release_camera()
        self._frame_head()

        if self.animated:
            # No set_control_effect here on purpose: loop() already leaves the
            # clip at full weight even under setBlend(animBlend=True) --
            # measured, 6943 head vertices move either way. Only a clip that
            # is being blended AGAINST another needs its weight set, which is
            # _begin_fade's job.
            self.actor.loop(self.config["idle_anim"])
            self._looping = self.config["idle_anim"]
        self._light()
        # mayChange=True keeps a live TextNode. The default flattens the text
        # into a bare PandaNode, after which the credit can no longer be read
        # back off the node -- and this credit is an attribution condition, so
        # it has to stay verifiable.
        self.credit = OnscreenText(
            text=self.config["credit"], pos=(0.0, -0.95), scale=0.04,
            fg=(0.8, 0.8, 0.85, 1.0), align=TextNode.ACenter, mayChange=True,
        )
        self._t = 0.0
        self._clip_start = 0.0
        self._pending = None        # (name, loop) deferred by MIN_DWELL
        self._fade = None           # (from, to, started, loop) while blending
        self._oneshot = None        # a non-looping clip holding the screen
        self._next_variety = None   # when the idle next breaks into variety
        self._last_variety = None
        self._rng = random.Random()
        if self.animated:
            # Without this every set_control_effect is ignored and the clips
            # hard-cut exactly as before. `animBlend` is camelCase on purpose:
            # Actor is a Python class, not a C++ binding, so it gets none of
            # the snake_case aliasing the rest of Panda3D has.
            self.actor.setBlend(animBlend=True)
        self.visible = True

    def _init_shader(self):
        """Install the PBR shader the glTF materials are written against.

        Colour lives in each material's baseColorTexture, which Panda3D's
        fixed-function pipeline cannot sample -- without this the model renders
        with its textures loaded, bound, and entirely unused. Skipped when
        there is no window to compile shaders against.

        Initialised at most once per window. simplepbr installs a FilterManager
        over the display region and claims it; a second init finds the region
        already taken and dies with "Could not find appropriate DisplayRegion
        to filter", so building a second AvatarScene -- swapping models at
        runtime, say -- would crash rather than re-use the pipeline.
        """
        if self.base.win is None:
            return

        existing = getattr(self.base, "_mavis_pbr_pipeline", None)
        if existing is not None:
            self.pipeline = existing
            return

        import simplepbr

        self.pipeline = simplepbr.init(msaa_samples=0)
        self.base._mavis_pbr_pipeline = self.pipeline

    def _release_camera(self):
        """Take the camera away from ShowBase's default mouse trackball.

        `_frame_head` frames by moving the *actor* and leaving the camera at
        the origin. ShowBase installs a Trackball2D that writes its own
        transform onto `base.camera` every frame, so the first mouse drag in
        the window replaces the framed view with the trackball's pose and the
        avatar vanishes off-frame -- looking exactly like a crash. Nothing here
        wants a user-flyable camera; the framing is the whole point.

        Skipped when there is no window, matching `_init_shader`: a windowless
        base has no mouse interface to detach.
        """
        if self.base.win is None:
            return
        self.base.disableMouse()

    def _frame_head(self):
        """Place the actor so the head fills the frame, from measured bounds.

        Bounds are read *relative to the actor*. `get_tight_bounds()` with no
        argument reports the mesh's own untransformed space, which on a model
        carrying a scale above the meshes -- as the rescaled keanu export does
        -- is out by the scale factor and frames empty air.

        The near plane is pulled in to suit the computed distance. Panda3D
        defaults it to 1.0, and a head framed closer than that is entirely
        clipped away, which looks exactly like a model that failed to load.
        """
        self.actor.set_pos(0, 0, 0)
        head = self.actor.find(f"**/{self.config['head_mesh']}")

        if head.is_empty():
            low, high = self.actor.get_tight_bounds()
            head_height = max(high[2] - low[2], 1e-3) * HEAD_FRACTION
            center_z = high[2] - head_height / 2.0
        else:
            low, high = head.get_tight_bounds(self.actor)
            head_height = max(high[2] - low[2], 1e-3)
            center_z = (low[2] + high[2]) / 2.0
        # Centre horizontally as well as vertically. A bind pose happens to put
        # the head on the model's centreline, so framing only Z looked correct
        # until a clip shifted his weight and left him sitting off to one side.
        center_x = (low[0] + high[0]) / 2.0

        framed = head_height * FRAMING
        lens = self.base.camLens
        fov_v = lens.get_fov()[1] if lens is not None else DEFAULT_FOV
        distance = (framed / 2.0) / math.tan(math.radians(fov_v / 2.0))

        if lens is not None:
            lens.set_near(min(lens.get_near(), max(distance * 0.05, 0.01)))
        # +z lifts the actor, which lowers the camera's aim down his body.
        self.actor.set_pos(-center_x, distance, -center_z + framed * HEAD_RISE)

    def _light(self):
        key = DirectionalLight("key")
        key.set_color(Vec4(1.0, 0.95, 0.9, 1))
        key_np = self.base.render.attach_new_node(key)
        key_np.set_hpr(20, -20, 0)
        self.base.render.set_light(key_np)

        ambient = AmbientLight("ambient")
        ambient.set_color(Vec4(0.35, 0.35, 0.45, 1))
        self.base.render.set_light(self.base.render.attach_new_node(ambient))

    def set_mouth(self, amount: float) -> None:
        """Open the mouth. `amount` is 0 (shut) to 1 (fully open)."""
        self.mouth.set(amount)

    def idle(self, elapsed: float) -> None:
        """Keep him alive between questions: breathing, head drift, weight.

        A model with real clips needs nothing here -- Panda3D advances the
        animation off its own clock, and the clip already carries everything
        this method synthesises. Only a model without animation falls through
        to the procedural channels.
        """
        self._t = elapsed
        if not self.animated:
            self.actor.set_h(math.sin(elapsed * SWAY_RATE)
                             * self.config.get("sway", 12.0))
            self.motion.apply(elapsed)
            return
        self._advance_blend(elapsed)

    def play(self, name: str, loop: bool = True) -> bool:
        """Switch to another clip, e.g. "smoking". False if it has none.

        The switch cross-fades and may be DEFERRED: a clip that has been up for
        less than MIN_DWELL keeps the screen and the request is held, newest
        winning, until the dwell expires. A deferred request is never dropped
        -- dropping it is how the pose ends up disagreeing with what he is
        actually doing.
        """
        if not self.animated or name not in self.actor.getAnimNames():
            return False
        # Where he is already heading: mid-fade that is the incoming clip, not
        # the one still on screen. Re-requesting it must not restart anything.
        heading_for = self._fade[1] if self._fade else self._looping
        if name == heading_for:
            # Also cancels a deferred request: asking for the clip already on
            # screen means "stay here", and leaving the old pending in place
            # would walk him off to it seconds later for no reason.
            self._pending = None
            return True

        if name in URGENT:
            self._pending = None
            self._begin_fade(name, loop, snap=True)
            return True

        if self._looping is not None and (self._t - self._clip_start) < MIN_DWELL:
            self._pending = (name, loop)
            return True

        self._pending = None
        self._begin_fade(name, loop)
        return True

    def _begin_fade(self, name: str, loop: bool, snap: bool = False) -> None:
        """Start `name` and blend the outgoing clip out over CROSSFADE."""
        # A one-shot on screen is outgoing too: forgetting it made every change
        # away from a variety clip snap instead of fade.
        outgoing = self._fade[1] if self._fade else (self._looping or self._oneshot)
        self._oneshot = None
        (self.actor.loop if loop else self.actor.play)(name)
        self._show_prop(name)

        if snap or outgoing is None or outgoing == name:
            for clip in self.actor.get_anim_names():
                self.actor.set_control_effect(clip, 1.0 if clip == name else 0.0)
            self._fade = None
            self._looping = name if loop else None
            self._oneshot = None if loop else name
            self._clip_start = self._t
            return

        self.actor.set_control_effect(outgoing, 1.0)
        self.actor.set_control_effect(name, 0.0)
        self._fade = (outgoing, name, self._t, loop)

    def _advance_blend(self, elapsed: float) -> None:
        """Drive the cross-fade and release a deferred request. Called per frame."""
        if self._fade is not None:
            outgoing, incoming, started, loop = self._fade
            weight = _smoothstep((elapsed - started) / CROSSFADE)
            self.actor.set_control_effect(outgoing, 1.0 - weight)
            self.actor.set_control_effect(incoming, weight)
            if weight >= 1.0:
                self.actor.stop(outgoing)
                self.actor.set_control_effect(outgoing, 0.0)
                self._fade = None
                self._looping = incoming if loop else None
                self._oneshot = None if loop else incoming
                self._clip_start = elapsed

        if self._pending is not None and self._fade is None:
            if self._looping is None or (elapsed - self._clip_start) >= MIN_DWELL:
                name, loop = self._pending      # read BEFORE clearing it
                self._pending = None
                self._begin_fade(name, loop)

        self._vary(elapsed)

    def _vary(self, elapsed: float) -> None:
        """Break the idle loop into a variety clip now and then, and come back.

        Only ever from the idle clip and only when nothing else is moving: a
        conversational pose (smoking, dismiss) is never interrupted, and a
        variety clip is itself left the moment the state machine asks for
        anything, because play() fades from it like any other clip.
        """
        variety = [c for c in self.config.get("idle_variety", ())
                   if c in self.actor.getAnimNames()]
        if not variety or self._fade is not None or self._pending is not None:
            return
        idle = self.config["idle_anim"]

        if self._oneshot in variety:
            # Start fading home while the clip still has CROSSFADE to run, so
            # he never freezes on its last frame.
            control = self.actor.getAnimControl(self._oneshot)
            left = ((control.getNumFrames() - 1 - control.getFrame())
                    / control.getFrameRate())
            if not control.isPlaying() or left <= CROSSFADE:
                self._begin_fade(idle, True)
            return

        if self._looping != idle:
            self._next_variety = None
            return
        if self._next_variety is None:
            self._next_variety = elapsed + self._rng.uniform(*VARIETY_EVERY)
        elif elapsed >= self._next_variety:
            self._next_variety = None
            choices = [c for c in variety if c != self._last_variety] or variety
            self._last_variety = self._rng.choice(choices)
            self._begin_fade(self._last_variety, False)

    def _attach_prop(self):
        """Parent the cigarette to a hand joint, hidden until a clip wants it.

        exposeJoint returns a node that follows the animated joint; a node
        found in the scene graph does not, and the prop would hang in the air
        while the hand moved away from it.
        """
        config = self.config.get("prop")
        if not config or not self.animated:
            return None
        # exposeJoint returns a fresh node whether or not the joint exists --
        # on a miss it only warns, and the prop would hang motionless at the
        # actor's origin, in frame. Ask the bundle directly instead.
        if self._bundle.find_child(config["joint"]) is None:
            return None
        hand = self.actor.expose_joint(None, "modelRoot", config["joint"])
        if hand is None or hand.is_empty():
            return None
        # The joints carry the rig's own unit scale (0.025 here), so a prop
        # parented to one arrives 40x too small and its offsets mean 40x less
        # than they read. Undo that, and keep `pos` honest metres.
        joint_scale = hand.get_scale(self.base.render)[0] or 1.0
        factor = 1.0 / joint_scale
        cigarette = props.make_cigarette()
        cigarette.reparent_to(hand)
        cigarette.set_scale(factor)
        cigarette.set_pos(*(offset * factor for offset in config["pos"]))
        cigarette.set_hpr(*config["hpr"])
        cigarette.hide()
        return cigarette

    def _show_prop(self, clip: str) -> None:
        if self.prop is None:
            return
        wanted = clip in self.config.get("prop", {}).get("clips", ())
        (self.prop.show if wanted else self.prop.hide)()

    def show_notice(self, text: str) -> None:
        """Degraded states must be visible -- never fail silently. "" clears."""
        if getattr(self, "_notice", None) is None:
            self._notice = OnscreenText(
                text="", pos=(0.0, 0.88), scale=0.05,
                fg=(1.0, 0.6, 0.3, 1.0), align=TextNode.ACenter, mayChange=True)
        self._notice.setText(text)

    def show_caption(self, text: str) -> None:
        """His answer, rendered so it reads with the sound off. "" clears.

        Anchored at CAPTION_TOP and grows DOWNWARD, so the anchor alone
        guarantees nothing: what matters is where the last row lands. The
        credit below it is an attribution condition and must stay readable
        while he talks, so the gap is sized for the worst case -- wordwrap
        breaks on whitespace only, so a hyphen-heavy answer ("tier-pool
        drawdown-breaker...") packs into far more rows than prose of the same
        length, and MAVIS_MAX_ANSWER_CHARS can raise the cap to 420.
        test_caption_never_covers_the_credit pins this.
        """
        if getattr(self, "_caption", None) is None:
            self._caption = OnscreenText(
                text="", pos=(0.0, CAPTION_TOP), scale=0.04,
                fg=(0.92, 0.92, 0.95, 1.0), align=TextNode.ACenter,
                mayChange=True, wordwrap=30)
        self._caption.setText(text)
        if not text:
            return
        # Measure, don't predict. Row count is not a function of length:
        # wordwrap breaks on whitespace only, so one 34-character hyphenated
        # token occupies a whole row, and 420 such characters ran to z=-1.198
        # -- past the credit and off the bottom of the frame. Trim from the
        # end until the last row clears the floor.
        while len(text) > 1 and self._caption.getTightBounds()[0][2] <= CAPTION_FLOOR:
            text = text[:max(1, len(text) - 16)]
            self._caption.setText(text.rstrip() + "...")

    def show(self) -> None:
        self.actor.show()
        self.credit.show()
        if getattr(self, "_notice", None) is not None:
            self._notice.show()
        if getattr(self, "_caption", None) is not None:
            self._caption.show()
        self.visible = True

    def hide(self) -> None:
        self.actor.hide()
        self.credit.hide()
        # The notice lives in aspect2d, so hiding the actor leaves it floating
        # over the bare desktop now that the window is transparent.
        if getattr(self, "_notice", None) is not None:
            self._notice.hide()
        if getattr(self, "_caption", None) is not None:
            self._caption.hide()
        self.visible = False
