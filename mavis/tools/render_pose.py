"""Render the avatar to a PNG so a change can be SEEN, not assumed.

Animation defects -- a prop intersecting a hand, a pose that reads wrong --
are invisible to the test suite and to `getTightBounds`. This renders
offscreen, so it works over SSH and in this sandbox where screencapture does
not, and the PNG can be looked at directly.

  tools/render_pose.py --clip smoking --frame 0 --look ValveBiped.Bip01_R_Hand

Frames are absolute; --frames renders several in one process (loading the
93MB model dominates the runtime, so batching matters).
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from panda3d.core import loadPrcFileData

loadPrcFileData("", "window-type offscreen\naudio-library-name null\n"
                    "hardware-animated-vertices false")

from direct.showbase.ShowBase import ShowBase          # noqa: E402
from panda3d.core import Filename, Vec3                # noqa: E402

from avatar import scene as scene_mod                  # noqa: E402


def _frame_on(base, target, distance, out):
    """Point the camera at `target` (a NodePath) from `distance` metres."""
    base.camera.set_pos(target.get_pos(base.render) + Vec3(distance, -distance, distance * 0.35))
    base.camera.look_at(target)
    # The near plane defaults to 1.0; a hand framed at 0.3m would be clipped
    # away entirely and the PNG would look empty rather than wrong.
    base.camLens.set_near(0.01)
    # taskMgr.step(), not graphicsEngine.render_frame(): simplepbr feeds
    # camera_world_position to its shader from a TASK, and without the main
    # loop that task never runs -- rendering directly asserts on the missing
    # shader input. Several steps because a pose is not applied to the
    # geometry until frames have actually been drawn.
    for _ in range(3):
        base.taskMgr.step()
    base.win.save_screenshot(Filename.from_os_specific(str(out)))
    print(f"wrote {out}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--avatar", default="keanu")
    ap.add_argument("--clip", default=None)
    ap.add_argument("--frames", default="0", help="comma-separated frame numbers")
    ap.add_argument("--look", default=None, help="joint name to centre on")
    ap.add_argument("--distance", type=float, default=0.35)
    ap.add_argument("--out", default="/tmp/pose")
    args = ap.parse_args()

    base = ShowBase()
    sc = scene_mod.AvatarScene(base, args.avatar)
    print("clips:", sc.actor.get_anim_names())

    if args.look:
        target = sc.actor.expose_joint(None, "modelRoot", args.look)
        if target is None or target.is_empty():
            print(f"no joint {args.look}", file=sys.stderr)
            return 1
    else:
        target = sc.actor

    for frame in [int(f) for f in args.frames.split(",")]:
        if args.clip:
            # Blending is on, so a clip posed at its default weight of zero
            # renders as whatever idle left behind -- every clip looked alike.
            for clip in sc.actor.get_anim_names():
                sc.actor.set_control_effect(clip, 1.0 if clip == args.clip else 0.0)
            sc.actor.pose(args.clip, frame)
            sc._show_prop(args.clip)
        base.taskMgr.step()
        _frame_on(base, target, args.distance, f"{args.out}-{args.clip}-{frame}.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
