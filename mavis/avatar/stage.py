"""The room behind the glass in portal mode: walls, grid, lights, shadow.

Why a room at all: off-axis projection on an EMPTY background moves nothing
you can see -- the eye reads depth from things at different distances sliding
past each other. The walls flush with the screen's edges are what you watch
open up as you lean, and his shadow on the back wall is the single strongest
"he is physically in there" cue (it is the "virtual shadow" half of the
reel). Everything here is geometry built in code: no new asset to license.

Layout, in the portal frame (metres, screen at y=0, see `portal`):
  * the room is LARGER than the window -- you look through the glass into a
    room, not into a screen-sized box. A box flush with the screen's edges
    was tried first and fails: he stands 30cm back, where the window shows
    half again its own height, so anything framed to fill it is taller than
    the box and the ceiling sliced through his head. Sized instead to what
    the window reveals at his depth, the walls sit just outside the frame
    from the centre and swing into view as you lean;
  * the floor is at his feet: he is framed from the belt up, so it is out of
    sight unless you crouch and look down into the room.
"""
from panda3d.core import (AmbientLight, BitMask32, CardMaker, NodePath, PNMImage,
                          PointLight, SamplerState, Spotlight, Texture,
                          TransparencyAttrib, Vec4)

# How far the back wall sits behind his head.
BACK_GAP = 0.32
# One grid cell, metres. Roughly a tile's worth of visual frequency at a
# laptop's distance: dense enough to read as a surface, sparse enough that
# the lines slide visibly when you move.
GRID_CELL = 0.04
# Bright enough that the key light makes a visible pool on the back wall --
# his shadow is only legible as a hole in that pool. Near-black walls (the
# first try) swallowed it completely.
WALL_RGB = (0.12, 0.12, 0.145)
LINE_RGB = (0.55, 0.06, 0.08)       # the reel's red, dimmed: neon behind glass
# Camera-mask bit the key light's shadow camera draws. Anything hidden from it
# casts no shadow. The glass edge needs that: it sits in front of the room,
# between the key light and the walls, and threw a thin dark line across the
# left wall that read as a rendering glitch.
SHADOW_BIT = BitMask32.bit(5)


def _grid_texture(size: int = 256, line_px: int = 3) -> Texture:
    img = PNMImage(size, size, 3)
    img.fill(*WALL_RGB)
    for i in range(size):
        for j in range(line_px):
            img.set_xel(i, j, *LINE_RGB)
            img.set_xel(j, i, *LINE_RGB)
    tex = Texture("mavis-grid")
    tex.load(img)
    tex.set_wrap_u(SamplerState.WM_repeat)
    tex.set_wrap_v(SamplerState.WM_repeat)
    tex.set_minfilter(SamplerState.FT_linear_mipmap_linear)
    tex.set_anisotropic_degree(8)
    return tex


def _card(parent, name, width, height, tex):
    cm = CardMaker(name)
    cm.set_frame(-width / 2.0, width / 2.0, -height / 2.0, height / 2.0)
    cm.set_has_normals(True)
    cm.set_uv_range((0, 0), (width / GRID_CELL, height / GRID_CELL))
    node = parent.attach_new_node(cm.generate())
    node.set_texture(tex)
    node.set_two_sided(False)
    return node


def build_room(render, screen, width: float, top: float, depth: float,
               floor_z: float) -> NodePath:
    """Build the room behind the screen.

    `width` and `top` give the room's cross-section (centred on x, from
    `floor_z` up to `top`); `depth` is the back wall's y. The bright edge
    marking the glass always follows the SCREEN, not the room.
    """
    room = render.attach_new_node("mavis-room")
    tex = _grid_texture()
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

    # A thin bright edge where the walls meet the glass. The reel's monitor
    # bezel does this job for free; a laptop's black bezel does not, and
    # without it the room's mouth vanishes into the bezel.
    edge = _frame_lines(room, screen.width, screen.height)
    edge.set_transparency(TransparencyAttrib.M_alpha)
    return room


def _frame_lines(parent, w, h, thickness=0.0015):
    frame = parent.attach_new_node("mouth")
    cm = CardMaker("mouth-edge")
    for name, (x0, x1, z0, z1) in {
        "top": (-w / 2, w / 2, h / 2 - thickness, h / 2),
        "bottom": (-w / 2, w / 2, -h / 2, -h / 2 + thickness),
        "left": (-w / 2, -w / 2 + thickness, -h / 2, h / 2),
        "right": (w / 2 - thickness, w / 2, -h / 2, h / 2),
    }.items():
        cm.set_frame(x0, x1, z0, z1)
        card = frame.attach_new_node(cm.generate())
        card.set_name(name)
        card.set_y(0.002)
        card.set_color(LINE_RGB[0], LINE_RGB[1], LINE_RGB[2], 0.9)
    frame.set_light_off(1)
    frame.hide(SHADOW_BIT)
    return frame


def light_room(render, target: NodePath, screen, depth: float):
    """Key spot that throws his shadow on the back wall, red rim, low fill.

    Returns the lights' NodePaths so a caller can tear them down. The key is
    a Spotlight, not a DirectionalLight: its shadow frustum is a cone that
    naturally fits a small room, where a directional light's orthographic
    shadow camera has to be sized by hand and silently crops the shadow when
    it is not.
    """
    lights = []

    key = Spotlight("portal-key")
    key.set_color(Vec4(2.4, 2.2, 2.0, 1))
    key.set_shadow_caster(True, 2048, 2048)
    key.set_camera_mask(SHADOW_BIT)
    key.get_lens().set_fov(80)
    key.get_lens().set_near_far(0.05, depth + 2.0)
    key_np = render.attach_new_node(key)
    # Up and to the right of the viewer, in front of the glass: the shadow
    # falls down and to his left on the back wall, where it is in view.
    key_np.set_pos(screen.width * 0.9, -0.35, screen.height * 1.1)
    key_np.look_at(target)
    render.set_light(key_np)
    lights.append(key_np)

    rim = PointLight("portal-rim")
    rim.set_color(Vec4(0.9, 0.08, 0.1, 1))
    rim.set_attenuation((1, 0, 6))
    rim_np = render.attach_new_node(rim)
    rim_np.set_pos(-screen.width * 0.42, depth * 0.85, screen.height * 0.35)
    render.set_light(rim_np)
    lights.append(rim_np)

    fill = AmbientLight("portal-fill")
    fill.set_color(Vec4(0.10, 0.10, 0.13, 1))
    fill_np = render.attach_new_node(fill)
    render.set_light(fill_np)
    lights.append(fill_np)
    return lights
