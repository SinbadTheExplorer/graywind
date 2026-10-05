"""Glow boost, soft shadows: the parts of the look that run headless."""
import pytest
from panda3d.core import loadPrcFileData

loadPrcFileData("", "window-type none\naudio-library-name null\n"
                    "hardware-animated-vertices false")

from direct.showbase.ShowBase import ShowBase  # noqa: E402

from avatar import look, scene  # noqa: E402


@pytest.fixture(scope="module")
def base():
    b = ShowBase()
    yield b
    b.destroy()


def _max_emission(actor):
    out = 0.0
    for mat in actor.find_all_materials():
        if mat.has_emission():
            e = mat.get_emission()
            out = max(out, e[0], e[1], e[2])
    return out


def test_glow_boost_multiplies_emission_and_never_compounds(base):
    """Panda3D caches loaded models, so boosting the shared materials in
    place would multiply again on every swap back: 16, 256, 4096..."""
    reg = scene.all_avatars()
    plain = dict(reg, **{"mech-bust": dict(reg["mech-bust"], glow=1.0)})
    sc = scene.AvatarScene(base, "mech-bust", registry=plain)
    base_glow = _max_emission(sc.actor)
    sc._teardown()
    assert base_glow > 0

    boosted = dict(reg, **{"mech-bust": dict(reg["mech-bust"], glow=16.0),
                           "box": {"path": str(scene.EXTRA_DIR / "mech-bust" / "mech_bust.glb"),
                                   "credit": "x", "mouth": {"kind": "none"}}})
    sc = scene.AvatarScene(base, "mech-bust", registry=boosted)
    assert _max_emission(sc.actor) == pytest.approx(base_glow * 16, rel=1e-4)
    for _ in range(3):
        sc.swap("box")
        sc.swap("mech-bust")
    assert _max_emission(sc.actor) == pytest.approx(base_glow * 16, rel=1e-4)
    sc._teardown()


def test_soft_shadows_patch_is_idempotent_and_replaces_the_single_tap():
    from simplepbr.shaders import shaders
    assert look.soften_shadows()
    assert look.soften_shadows()                  # second call: no double patch
    src = shaders["simplepbr.frag"]
    assert src.count("poisson[16]") == 1
    assert look._HARD_SHADOW not in src


def test_soft_shadows_refuse_an_unfamiliar_simplepbr(monkeypatch):
    """A changed simplepbr keeps its own shadows, not a broken shader."""
    from simplepbr.shaders import shaders
    monkeypatch.setitem(shaders, "simplepbr.frag", "void main() {}")
    assert look.soften_shadows() is False
    assert shaders["simplepbr.frag"] == "void main() {}"


def test_glow_threshold_sits_above_lit_surfaces():
    """At 0.85 the softbox's reflection on the mech's crest glowed into a
    white blob at the top of the frame. Only light sources may pass."""
    assert look.THRESHOLD > 1.0
    assert "max(c.r, max(c.g, c.b))" in look._BRIGHT    # red lights count
