"""The set behind the glass in portal mode: room, lights, shadow, film look.

Why a room at all: off-axis projection on an EMPTY background moves nothing
you can see -- the eye reads depth from things at different distances sliding
past each other. His shadow on the back wall is the single strongest "he is
physically in there" cue (the "virtual shadow" half of the reel). Everything
here is built in code: no new asset to license.

The LOOK is matched to the reference reel (@ojrgb, TouchDesigner), not to a
demo. A first pass used a bright grid box -- the classic head-tracking demo
look -- and read as a tech demo next to the reel. What the reel actually
does, and this copies:
  * low-key light: one hard key from above, everything else falling to near
    black, so the subject is carved out by highlights rather than lit evenly;
  * a dim, cool, textured back wall (grimy concrete, not a pattern) that is
    barely there except where the key spills onto it -- which is exactly
    where the shadow lands;
  * a coloured rim from behind (the reel's red) separating him from the wall;
  * a camera-like finish: vignette and moving film grain over the frame.

Layout, in the portal frame (metres, screen at y=0, see `portal`):
  * the room is LARGER than the window -- you look through the glass into a
    room, not into a screen-sized box. A box flush with the screen's edges
    was tried first and fails: the window reveals more than its own height
    at his depth, so anything framed to fill it was taller than the box and
    the ceiling sliced through his head;
  * the floor is at his feet, out of sight unless you crouch.
"""
import random

from panda3d.core import (AmbientLight, CardMaker, NodePath, PerlinNoise2,
                          PNMImage, PointLight, SamplerState, Spotlight,
                          Texture, TextureStage, TransparencyAttrib, Vec4)

# How far the back wall sits behind his head. Close, as in the reel: the
# shadow stays near him and big, instead of a small far-off silhouette.
BACK_GAP = 0.20
# One repeat of the concrete texture, metres.
TILE = 0.75
# Concrete: dark blue-grey, the reel's wall. Values are albedo, before light.
CONCRETE_RGB = (0.065, 0.08, 0.12)
RIM_RGB = (0.85, 0.06, 0.05)         # the reel's red, kept to an accent
COOL_RIM_RGB = (0.25, 0.35, 0.6)


def _concrete_texture(size: int = 512, seed: int = 7) -> Texture:
    """Tileable-enough grimy concrete from layered Perlin noise and pits."""
    img = PNMImage(size, size, 3)
    octaves = [PerlinNoise2(scale, scale, 256, seed + i)
               for i, scale in enumerate((96.0, 32.0, 9.0, 3.0))]
    weights = (0.45, 0.30, 0.17, 0.08)
    rng = random.Random(seed)
    base_r, base_g, base_b = CONCRETE_RGB
    for x in range(size):
        for y in range(size):
            n = sum(w * o.noise(x, y) for w, o in zip(weights, octaves))
            v = max(0.0, min(1.5, 1.0 + 0.9 * n))
            img.set_xel(x, y, base_r * v, base_g * v, base_b * v)
    # Pits and stains: the speckle that makes a surface read as a surface
    # rather than as a smooth gradient.
    for _ in range(size * 6):
        x, y = rng.randrange(size), rng.randrange(size)
        k = rng.uniform(0.25, 0.7)
        r, g, b = img.get_xel(x, y)
        img.set_xel(x, y, r * k, g * k, b * k)
    tex = Texture("mavis-concrete")
    tex.load(img)
    # Repeat, not mirror: mirroring hides the seam but folds the noise into a
    # Rorschach blot that the eye finds instantly. At TILE metres a repeat is
    # wider than the window, so the seam is rarely in view at all.
    tex.set_wrap_u(SamplerState.WM_repeat)
    tex.set_wrap_v(SamplerState.WM_repeat)
    tex.set_minfilter(SamplerState.FT_linear_mipmap_linear)
    tex.set_anisotropic_degree(8)
    return tex


def _card(parent, name, width, height, tex):
    cm = CardMaker(name)
    cm.set_frame(-width / 2.0, width / 2.0, -height / 2.0, height / 2.0)
    cm.set_has_normals(True)
    cm.set_uv_range((0, 0), (width / TILE, height / TILE))
    node = parent.attach_new_node(cm.generate())
    node.set_texture(tex)
    node.set_two_sided(False)
    return node


def build_room(render, screen, width: float, top: float, depth: float,
               floor_z: float) -> NodePath:
    """Build the room behind the screen.

    `width` and `top` give the room's cross-section (centred on x, from
    `floor_z` up to `top`); `depth` is the back wall's y.
    """
    room = render.attach_new_node("mavis-room")
    tex = _concrete_texture()
    w = width
    height = top - floor_z
    mid_z = (top + floor_z) / 2.0

    # CardMaker cards lie in XZ and face -y, i.e. toward the viewer.
    back = _card(room, "back", w, height, tex)
    back.set_pos(0, depth, mid_z)

    left = _card(room, "left", depth, height, tex)
    left.set_hpr(90, 0, 0)                  # face +x, into the room
    left.set_pos(-w / 2.0, depth / 2.0, mid_z)

    right = _card(room, "right", depth, height, tex)
    right.set_hpr(-90, 0, 0)                # face -x
    right.set_pos(w / 2.0, depth / 2.0, mid_z)

    ceiling = _card(room, "ceiling", w, depth, tex)
    ceiling.set_hpr(0, 90, 0)               # face -z, down into the room
    ceiling.set_pos(0, depth / 2.0, top)

    floor = _card(room, "floor", w, depth, tex)
    floor.set_hpr(0, -90, 0)                # face +z
    floor.set_pos(0, depth / 2.0, floor_z)
    return room


def light_room(render, target: NodePath, screen, depth: float):
    """Low-key rig: hard top key with his shadow, red rim, cool kicker, no fill.

    Returns the lights' NodePaths so a caller can tear them down. The key is
    a Spotlight, not a DirectionalLight: its cone gives a pool of light that
    falls off into darkness (the low-key look needs that falloff), and its
    shadow frustum naturally fits a small room, where a directional light's
    orthographic shadow camera must be sized by hand and silently crops.
    """
    lights = []
    head = target.get_pos(render)

    key = Spotlight("portal-key")
    key.set_color(Vec4(3.6, 3.5, 3.4, 1))
    key.set_shadow_caster(True, 2048, 2048)
    # Wide enough that the cone's EDGE never shows. simplepbr ignores the
    # spot exponent and cuts the cone off hard, so a tight cone drew a crisp
    # stage-spotlight disc on the back wall. The falloff to dark corners
    # comes from the vignette in FilmFinish instead.
    key.get_lens().set_fov(80)
    key.get_lens().set_near_far(0.05, depth + 2.0)
    key_np = render.attach_new_node(key)
    # High and a little to the viewer's right, in front of the glass: the
    # shadow drops onto the back wall below and to his left, in view, and
    # the brow, nose and shoulders catch top light as in the reel.
    key_np.set_pos(head[0] + screen.width * 0.55, -0.30, head[2] + screen.height * 1.5)
    key_np.look_at(head[0], head[1], head[2] - 0.03)
    render.set_light(key_np)
    lights.append(key_np)

    # Rims sit BEHIND him, near the wall, so they light his edges and not his
    # front; quadratic falloff keeps them off the wall's far corners.
    rim = PointLight("portal-rim")
    rim.set_color(Vec4(*RIM_RGB, 1))
    rim.set_attenuation((1, 0, 30))
    rim_np = render.attach_new_node(rim)
    rim_np.set_pos(head[0] - screen.width * 0.35, head[1] + 0.12, head[2] + 0.02)
    render.set_light(rim_np)
    lights.append(rim_np)

    kicker = PointLight("portal-kicker")
    kicker.set_color(Vec4(*COOL_RIM_RGB, 1))
    kicker.set_attenuation((1, 0, 30))
    kicker_np = render.attach_new_node(kicker)
    kicker_np.set_pos(head[0] + screen.width * 0.38, head[1] + 0.10, head[2] + 0.06)
    render.set_light(kicker_np)
    lights.append(kicker_np)

    # Not zero: PBR with no ambient renders unlit faces pure black, which
    # reads as clipped rather than as shadow.
    fill = AmbientLight("portal-fill")
    fill.set_color(Vec4(0.035, 0.04, 0.06, 1))
    fill_np = render.attach_new_node(fill)
    render.set_light(fill_np)
    lights.append(fill_np)
    return lights


def studio_env_map(size: int = 64):
    """A virtual photo studio for METAL to reflect: dark, one overhead softbox.

    PBR metal has almost no diffuse colour -- it shows what it reflects. With
    no environment it reflects black, and the mech (the reel's model) came out
    a murky silhouette. The reel's metal reads as metal because of bright top
    highlights; a softbox overhead gives exactly that, and a faint panel on
    the viewer's side keeps faces from going pitch black. Generated, not
    shipped: no HDR file to license or carry.

    simplepbr samples this with the WORLD reflection vector, so faces are
    world axes: 0 +x, 1 -x, 2 +y (into the screen), 3 -y (toward the viewer),
    4 +z (up), 5 -z (down).
    """
    import simplepbr

    def face(fill, box=None, box_rgb=(0, 0, 0), soft=0.25):
        img = PNMImage(size, size, 3)
        img.fill(*fill)
        if box:
            x0, y0, x1, y1 = (int(v * size) for v in box)
            for x in range(size):
                for y in range(size):
                    # Distance outside the box, in face widths: a soft edge,
                    # so highlights are smooth gradients, not hard stripes.
                    dx = max(x0 - x, 0, x - x1) / size
                    dy = max(y0 - y, 0, y - y1) / size
                    k = max(0.0, 1.0 - (dx * dx + dy * dy) ** 0.5 / soft)
                    if k > 0:
                        img.set_xel(x, y, *(f + (b - f) * k for f, b in zip(fill, box_rgb)))
        return img

    dark = (0.012, 0.014, 0.022)
    faces = [
        face(dark),                                            # +x
        face(dark),                                            # -x
        face((0.03, 0.01, 0.01)),                              # +y behind him: a red hint
        face(dark, (0.25, 0.3, 0.75, 0.7), (0.22, 0.24, 0.30)),  # -y viewer side: dim fill panel
        face(dark, (0.2, 0.2, 0.8, 0.8), (1.0, 0.98, 0.95)),   # +z overhead softbox
        face((0.005, 0.005, 0.008)),                           # -z floor
    ]
    cube = Texture("mavis-studio")
    cube.setup_cube_map(size, Texture.T_unsigned_byte, Texture.F_rgb)
    for i, img in enumerate(faces):
        cube.load(img, i, 0)
    return simplepbr.EnvMap(cube, blocking_prepare=True)


class FilmFinish:
    """Vignette + moving grain over the frame, the reel's camera finish.

    Drawn as two cards in render2d's BACKGROUND bin, so they sit over the 3D
    image but under the captions and credit -- text stays crisp. No shader:
    simplepbr owns the post-process chain and a second filter would fight it.
    """

    GRAIN_ALPHA = 0.07
    VIGNETTE_ALPHA = 0.92

    def __init__(self, render2d, seed: int = 11):
        self._rng = random.Random(seed)
        self.root = render2d.attach_new_node("mavis-film")
        self.root.set_bin("background", 10)
        self.root.set_depth_write(False)
        self.root.set_depth_test(False)
        self.root.set_light_off(1)
        self.root.set_transparency(TransparencyAttrib.M_alpha)

        self.vignette = self._fullscreen("vignette", self._vignette_texture())
        self.vignette.set_bin("background", 11)
        self.grain = self._fullscreen("grain", self._grain_texture(), repeat=3.0)
        self.grain.set_bin("background", 12)

    def _fullscreen(self, name, tex, repeat=1.0):
        cm = CardMaker(name)
        cm.set_frame(-1, 1, -1, 1)
        cm.set_uv_range((0, 0), (repeat, repeat))
        card = self.root.attach_new_node(cm.generate())
        card.set_texture(tex)
        return card

    def _vignette_texture(self, size=256):
        img = PNMImage(size, size, 4)
        for x in range(size):
            for y in range(size):
                dx = (x / (size - 1)) * 2 - 1
                dy = (y / (size - 1)) * 2 - 1
                r = min(1.0, (dx * dx + dy * dy) ** 0.5 / 1.414)
                # Clear centre, smooth roll-off into the corners.
                a = max(0.0, (r - 0.25) / 0.75)
                a = a * a * (3 - 2 * a) * self.VIGNETTE_ALPHA
                img.set_xel_a(x, y, 0, 0, 0, a)
        tex = Texture("mavis-vignette")
        tex.load(img)
        tex.set_wrap_u(SamplerState.WM_clamp)
        tex.set_wrap_v(SamplerState.WM_clamp)
        return tex

    def _grain_texture(self, size=256):
        img = PNMImage(size, size, 4)
        for x in range(size):
            for y in range(size):
                v = self._rng.random()
                img.set_xel_a(x, y, v, v, v, self.GRAIN_ALPHA)
        tex = Texture("mavis-grain")
        tex.load(img)
        tex.set_wrap_u(SamplerState.WM_repeat)
        tex.set_wrap_v(SamplerState.WM_repeat)
        tex.set_magfilter(SamplerState.FT_nearest)
        return tex

    def step(self) -> None:
        """Jump the grain every frame. Static grain reads as a dirty screen."""
        self.grain.set_tex_offset(TextureStage.get_default(),
                                  self._rng.random(), self._rng.random())
