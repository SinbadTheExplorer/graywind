"""Portal mode's two camera effects from the reel: soft shadows and glow.

Both hook into simplepbr rather than replacing it -- simplepbr owns the PBR
shader and the post-process chain, and a second filter system (Panda3D's
CommonFilters) would fight it for the same display region.

* Soft shadows. simplepbr samples its shadow map ONCE, which gives a hard,
  stair-stepped edge; the reel's shadow on the wall is soft. `soften_shadows`
  patches simplepbr's own fragment-shader source, before any shader is built,
  to average a 16-tap Poisson disc instead.

* Glow. The reel's eye-lights bleed light into the air around them. simplepbr
  has no bloom, so `Bloom` adds the classic chain to its FilterManager: keep
  only pixels brighter than THRESHOLD, blur them at quarter resolution
  (separable Gaussian, two passes), and add the result to the scene just
  before simplepbr's own tonemapping -- so it is in HDR and tonemaps like
  real light, rather than being pasted over the finished image.

Every shader here goes through simplepbr's loader with its defines, so the
GLSL 120 written below is rewritten to 330 on a core-profile context (macOS)
exactly as simplepbr's own shaders are.
"""
from panda3d.core import Texture

# Shadow softness: Poisson-disc radius in shadow-map UV units. At the 2048px
# map in stage.light_room, 0.0025 is ~5 texels: soft enough to lose the
# stair-steps and read as a real penumbra, tight enough that the silhouette
# still reads as HIM.
SHADOW_RADIUS = 0.0025

# Glow. HDR luminance above which a pixel glows. Above the brightest LIT
# surface, so only light SOURCES glow: at 0.85 the softbox's reflection on
# the mech's crest, just above the frame edge, glowed and only its halo was in
# frame -- a stray white blob at the top. Emissive parts are lifted well past
# this per model with `glow` in avatar.json (the mech's eyes use 6).
THRESHOLD = 1.3
# How much of the blurred bright-pass is added back.
STRENGTH = 0.9

_POISSON = (
    (-0.942, -0.399), (0.946, -0.769), (-0.094, -0.929), (0.345, 0.294),
    (-0.916, 0.458), (-0.815, -0.879), (-0.383, 0.277), (0.975, 0.756),
    (0.443, -0.975), (0.537, -0.474), (-0.265, -0.419), (0.792, 0.191),
    (-0.242, 0.997), (-0.814, 0.914), (0.200, 0.786), (0.144, -0.141),
)

_HARD_SHADOW = """#ifdef USE_330
    float shadow = texture(shadowmap, light_space_coords);
#else
    float shadow = shadow2D(shadowmap, light_space_coords).r;
#endif
    return shadow;"""


def _soft_shadow_source() -> str:
    taps = ",\n        ".join(f"vec2({x}, {y})" for x, y in _POISSON)
    return f"""vec2 poisson[16] = vec2[16](
        {taps});
    float shadow = 0.0;
    for (int i = 0; i < 16; ++i) {{
        vec3 tap = vec3(light_space_coords.xy + poisson[i] * {SHADOW_RADIUS}, light_space_coords.z);
#ifdef USE_330
        shadow += texture(shadowmap, tap);
#else
        shadow += shadow2D(shadowmap, tap).r;
#endif
    }}
    return shadow / 16.0;"""


def soften_shadows() -> bool:
    """Patch simplepbr's shader source in place. Call BEFORE simplepbr.init.

    Returns False (and changes nothing) if simplepbr's shadow code is not the
    text this was written against -- an upgraded simplepbr must fall back to
    its own hard shadows, not to a shader that fails to compile.
    """
    from simplepbr.shaders import shaders
    source = shaders["simplepbr.frag"]
    if "poisson[16]" in source:
        return True
    if _HARD_SHADOW not in source:
        return False
    shaders["simplepbr.frag"] = source.replace(_HARD_SHADOW, _soft_shadow_source())
    return True


_BRIGHT = """#version 120
#ifdef USE_330
    #define texture2D texture
    out vec4 o_color;
#endif
uniform sampler2D tex;
uniform float threshold;
varying vec2 v_texcoord;
void main() {
    vec3 c = texture2D(tex, v_texcoord).rgb;
    // Strongest channel, NOT perceptual luminance: luminance weights red at
    // 0.21, so the mech's pure-red eye-lights at 6x scored 1.28 and never
    // glowed. A saturated light is a bright light.
    float luma = max(c.r, max(c.g, c.b));
    // Soft knee: ramps in over 0.25 above the threshold instead of switching
    // on, so highlights do not pop in and out of glowing as he moves.
    float k = clamp((luma - threshold) / 0.25, 0.0, 1.0);
    vec4 outc = vec4(c * k * k, 1.0);
#ifdef USE_330
    o_color = outc;
#else
    gl_FragColor = outc;
#endif
}
"""

_BLUR = """#version 120
#ifdef USE_330
    #define texture2D texture
    out vec4 o_color;
#endif
uniform sampler2D tex;
uniform vec2 step_uv;
varying vec2 v_texcoord;
void main() {
    // 9-tap Gaussian folded into 5 bilinear fetches.
    vec3 c = texture2D(tex, v_texcoord).rgb * 0.2270270270;
    c += texture2D(tex, v_texcoord + step_uv * 1.3846153846).rgb * 0.3162162162;
    c += texture2D(tex, v_texcoord - step_uv * 1.3846153846).rgb * 0.3162162162;
    c += texture2D(tex, v_texcoord + step_uv * 3.2307692308).rgb * 0.0702702703;
    c += texture2D(tex, v_texcoord - step_uv * 3.2307692308).rgb * 0.0702702703;
#ifdef USE_330
    o_color = vec4(c, 1.0);
#else
    gl_FragColor = vec4(c, 1.0);
#endif
}
"""

# simplepbr's tonemap, with the bloom added in HDR before the curve.
_TONEMAP_HOOK = "    vec3 color = tex_color.rgb;\n"
_TONEMAP_BLOOM = ("    vec3 color = tex_color.rgb"
                  " + texture2D(bloom, v_texcoord).rgb * bloom_strength;\n")


def _register(name: str, source: str) -> None:
    from simplepbr.shaders import shaders
    shaders[name] = source


class Bloom:
    """Bright-pass -> blur X -> blur Y, added into simplepbr's tonemap pass."""

    def __init__(self, pipeline, threshold: float = THRESHOLD,
                 strength: float = STRENGTH):
        from simplepbr import _shaderutils as su
        from simplepbr.shaders import shaders

        post = pipeline._post_process_quad
        scene_tex = post.get_shader_input("tex").get_texture()
        fm = pipeline._filtermgr
        defines = {"USE_330": pipeline.use_330,
                   "IS_WEBGL": getattr(pipeline, "_is_webgl", False)}

        _register("mavis_bright.frag", _BRIGHT)
        _register("mavis_blur.frag", _BLUR)

        def stage(name, frag, src, div):
            tex = Texture(name)
            tex.set_format(Texture.F_rgba16)
            tex.set_component_type(Texture.T_float)
            quad = fm.render_quad_into(name, colortex=tex, div=div)
            if quad is None:
                raise RuntimeError(f"bloom: could not create the {name} buffer")
            quad.set_shader(su.make_shader(name, "post.vert", frag, defines))
            quad.set_shader_input("tex", src)
            return quad, tex

        self.bright_quad, bright = stage("mavis-bloom-bright", "mavis_bright.frag", scene_tex, 2)
        self.bright_quad.set_shader_input("threshold", threshold)
        self.blur_x, blur_x = stage("mavis-bloom-x", "mavis_blur.frag", bright, 4)
        self.blur_y, blur_y = stage("mavis-bloom-y", "mavis_blur.frag", blur_x, 4)
        # Step sizes are in UV units of the quarter-res buffers; they track the
        # window, so they are refreshed per frame in `step`.
        self._fm = fm
        self._set_steps()

        # simplepbr's tonemap, with the bloom texture folded in. Built from
        # simplepbr's own source so exposure, the curve and the LUT path are
        # untouched; refuse (keep simplepbr's shader) if the hook moved.
        tonemap = shaders["tonemap.frag"]
        if _TONEMAP_HOOK not in tonemap:
            raise RuntimeError("bloom: simplepbr's tonemap shader changed")
        tonemap = tonemap.replace(_TONEMAP_HOOK, _TONEMAP_BLOOM).replace(
            "uniform float exposure;",
            "uniform float exposure;\nuniform sampler2D bloom;\nuniform float bloom_strength;")
        _register("mavis_tonemap.frag", tonemap)
        tdefines = dict(defines, USE_SDR_LUT=bool(pipeline.sdr_lut))
        post.set_shader(su.make_shader("mavis-tonemap", "post.vert",
                                       "mavis_tonemap.frag", tdefines))
        post.set_shader_input("bloom", blur_y)
        post.set_shader_input("bloom_strength", strength)
        self.post = post
        self.strength = strength

    def _set_steps(self):
        x, y = self._fm.getScaledSize(1, 4, 1)
        x, y = max(int(x), 1), max(int(y), 1)
        self.blur_x.set_shader_input("step_uv", (1.0 / x, 0.0))
        self.blur_y.set_shader_input("step_uv", (0.0, 1.0 / y))

    def step(self) -> None:
        self._set_steps()

    def set_strength(self, strength: float) -> None:
        self.strength = strength
        self.post.set_shader_input("bloom_strength", strength)
