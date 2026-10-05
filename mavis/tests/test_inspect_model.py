"""The inspector's judgement calls, pinned on the committed mech."""
import pytest
from panda3d.core import loadPrcFileData

loadPrcFileData("", "window-type none\naudio-library-name null\n"
                    "hardware-animated-vertices false")

from avatar import scene  # noqa: E402
from tools import inspect_model  # noqa: E402

MECH = scene.EXTRA_DIR / "mech-bust" / "mech_bust.glb"


@pytest.fixture(scope="module")
def spec():
    return inspect_model.inspect(str(MECH))


def test_finds_the_head_the_jaw_hinge_and_keeps_a_good_clip(spec):
    assert spec["head_mesh"] == "mech_mech_head_mat_0"
    assert spec["mouth"] == {"kind": "joint", "joint": "jaw_07", "axis": "r",
                             "degrees": 14.0}
    # The deforming-clip check must NOT reject a clip that plays cleanly.
    assert spec["idle_anim"] == "anim"


def test_the_starter_credit_cannot_be_mistaken_for_a_real_one(spec):
    assert "EDIT ME" in spec["credit"]
