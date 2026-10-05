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
    character = actor.find("**/+Character")
    rigged = not character.is_empty()

    meshes = sorted({g.getName() for g in actor.findAllMatches("**/+GeomNode")})
    sliders = (sorted(set(_all_sliders(character.node().getBundle(0), [])))
               if rigged else [])
    joints = [j.getName() for j in actor.getJoints()] if rigged else []
    anims = list(actor.getAnimNames())

    # Armoured characters name it "Helmet" (the Spartan), busts "head". Of
    # the candidates take the BIGGEST: the first match alphabetically was the
    # Spartan's ear piece, "Helmet_Spartan_Ear_Mat_0".
    def size(name):
        lo, hi = actor.find(f"**/{name}").get_tight_bounds(actor)
        return (hi - lo).length()
    head = None
    for word in ("head", "helmet"):
        found = [m for m in meshes if word in m.lower()]
        if found:
            head = max(found, key=size)
            break
    jaw = next((j for j in joints if "jaw" in j.lower()), None)
    morph = next((m for m in MOUTH_MORPHS if m in sliders), None)
    if not rigged:
        # No skeleton: a static mesh. It nods along with speech instead.
        mouth = {"kind": "nod", "degrees": 3.0}
    elif morph:
        mouth = {"kind": "slider", "slider": morph, "gain": 1.0}
    elif jaw:
        # A mouth opens by turning the jaw about the head's LEFT-RIGHT axis
        # (world x, for a model facing the camera). Pick whichever of the
        # joint's local axes lines up with it; the other two skew the jaw
        # sideways. Guessing "p" for the mech bust skewed it -- its hinge is r.
        hinge = actor.expose_joint(None, "modelRoot", jaw)
        actor.update(force=True)
        local = {"h": (0, 0, 1), "p": (1, 0, 0), "r": (0, 1, 0)}
        axis = max(local, key=lambda a: abs(
            actor.get_relative_vector(hinge, local[a]).normalized()[0]))
        print(f"jaw     {jaw}: hinge axis {axis} (if it closes instead of "
              "opening, make degrees negative)")
        mouth = {"kind": "joint", "joint": jaw, "axis": axis, "degrees": 14.0}
    else:
        mouth = {"kind": "none"}
    idle = next((a for a in anims if "idle" in a.lower()), anims[0] if anims else None)
    if idle and rigged:
        # Some exports bind the mesh in one pose and store a different rest
        # pose; panda3d-gltf then applies the difference twice the moment any
        # clip plays (the Spartan's arms ballooned into wings). The tell: the
        # model gets much bigger when posed than when not.
        lo, hi = actor.get_tight_bounds()
        actor.pose(idle, 0)
        actor.update(force=True)
        plo, phi = actor.get_tight_bounds()
        grow = max((phi[i] - plo[i]) / max(hi[i] - lo[i], 1e-6) for i in range(3))
        if grow > 1.25:
            print(f"clip {idle!r} DEFORMS the mesh when played (posed size x{grow:.1f}); "
                  "left out -- the model will stand in its bind pose and sway")
            idle = None

    print(f"rigged  {rigged}" + ("" if rigged else
          "  (static mesh: no lip-sync or clips; it will sway and nod)"))
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
    else:
        # Without a head mesh the framing assumes a full figure (head = top
        # 19%). Busts and heads are far more head than that.
        spec["head_fraction"] = 0.19
        print("no head mesh found: set head_fraction to ~0.5 for a bust, "
              "~0.9 for a head on its own, 0.19 for a full figure")
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
