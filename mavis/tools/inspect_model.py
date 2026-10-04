"""Look inside a model and print a starter avatar.json for it.

Writing a drop-in's avatar.json needs three names nobody knows by heart: the
head mesh (for framing), the mouth morph or jaw joint (for lip-sync) and the
idle clip (for animation). This finds candidates for all three.

  .venv/bin/python -m tools.inspect_model assets/avatar/extra/robot/robot.glb

Then copy the printed JSON into assets/avatar/extra/robot/avatar.json and fix
the credit line by hand -- that one is a licence condition, not a guess.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from panda3d.core import loadPrcFileData

loadPrcFileData("", "window-type none\naudio-library-name null\n"
                    "hardware-animated-vertices false")

from direct.actor.Actor import Actor                   # noqa: E402
from direct.showbase.ShowBase import ShowBase          # noqa: E402
from panda3d.core import Filename                      # noqa: E402

# Morph names used by the common avatar pipelines, best first: ARKit
# blendshapes (VRoid, many Sketchfab exports), Ready Player Me, VRM, generic.
MOUTH_MORPHS = ("jawOpen", "mouthOpen", "viseme_aa", "A", "Fcl_MTH_A", "MouthOpen")

def _all_sliders(part, acc):
    if type(part).__name__ == "CharacterSlider":
        acc.append(part.getName())
    for i in range(part.getNumChildren()):
        _all_sliders(part.getChild(i), acc)
    return acc

def inspect(path: str) -> dict:
    base = ShowBase()
    # Panda3D searches its model path, not the working directory, so a
    # relative path that exists right here still comes back "not found".
    actor = Actor(Filename.from_os_specific(str(Path(path).resolve())))
    bundle = actor.find("**/+Character").node().getBundle(0)

    meshes = sorted({g.getName() for g in actor.findAllMatches("**/+GeomNode")})
    sliders = sorted(set(_all_sliders(bundle, [])))
    joints = [j.getName() for j in actor.getJoints()]
    anims = list(actor.getAnimNames())

    head = next((m for m in meshes if "head" in m.lower()), None)
    jaw = next((j for j in joints if "jaw" in j.lower()), None)
    morph = next((m for m in MOUTH_MORPHS if m in sliders), None)
    if morph:
        mouth = {"kind": "slider", "slider": morph, "gain": 1.0}
    elif jaw:
        # Axis and travel differ per rig: render with tools/render_pose.py
        # and adjust until the mouth opens rather than skews.
        mouth = {"kind": "joint", "joint": jaw, "axis": "p", "degrees": 14.0}
    else:
        mouth = {"kind": "none"}
    idle = next((a for a in anims if "idle" in a.lower()), anims[0] if anims else None)

    print(f"meshes  ({len(meshes)}): {meshes}")
    print(f"morphs  ({len(sliders)}): {sliders}")
    print(f"joints  ({len(joints)}), jaw-like: {[j for j in joints if 'jaw' in j.lower()]}")
    print(f"clips   ({len(anims)}): {anims}")
    low, high = actor.get_tight_bounds()
    print(f"height  {high[2] - low[2]:.3f} units (a person is ~1.7; ~170 means centimetres)")

    spec = {"model": Path(path).name,
            "credit": "Model: TITLE by AUTHOR (LICENCE) -- EDIT ME"}
    if head:
        spec["head_mesh"] = head
    spec["mouth"] = mouth
    if idle:
        spec["idle_anim"] = idle
    base.destroy()
    return spec

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    print("\nstarter avatar.json:\n" + json.dumps(inspect(sys.argv[1]), indent=2))
