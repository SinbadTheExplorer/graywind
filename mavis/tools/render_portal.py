"""Render portal mode from fixed eye positions, to SEE the parallax work.

The effect only exists for a moving viewer, so a single screenshot proves
nothing. This renders the same instant from several eyes -- centred, leaning
left, right, up, close -- side by side in one PNG. If it is working, the
window's EDGES stay put in every tile while the room and Johnny slide behind
them, and the side walls open up on the side you lean away from.

  tools/render_portal.py --avatar mech-bust --out /tmp/portal.png

No webcam involved: `look_from` is fed the eyes directly.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from panda3d.core import loadPrcFileData

loadPrcFileData("", "window-type offscreen\naudio-library-name null\n"
                    "hardware-animated-vertices false\nwin-size 604 392")

from direct.showbase.ShowBase import ShowBase          # noqa: E402
from panda3d.core import Filename, PNMImage            # noqa: E402

from avatar import portal                              # noqa: E402
from avatar import scene as scene_mod                  # noqa: E402

EYES = {
    "centre": (0.00, -0.60, 0.00),
    "left": (-0.22, -0.60, 0.00),
    "right": (0.22, -0.60, 0.00),
    "high": (0.00, -0.60, 0.18),
    "close": (0.00, -0.35, 0.00),
    "far-left-low": (-0.30, -0.80, -0.10),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--avatar", default="mech-bust")
    ap.add_argument("--out", default="/tmp/portal.png")
    ap.add_argument("--clip", default=None, help="hold this clip's frame 0")
    args = ap.parse_args()

    base = ShowBase()
    screen = portal.screen_from_env()
    sc = scene_mod.AvatarScene(base, args.avatar, portal=screen)
    if args.clip:
        sc.actor.pose(args.clip, 0)

    tiles = []
    for name, eye in EYES.items():
        sc.look_from(eye)
        sc.show_hud(f"JOHNNY // LOCKED   eye {-eye[1]:.2f}m   "
                    f"x{eye[0]:+.2f} z{eye[2]:+.2f}   cam 30fps")
        for _ in range(3):
            base.taskMgr.step()
        img = PNMImage()
        base.win.get_screenshot(img)
        tiles.append((name, img))

    w, h = tiles[0][1].get_x_size(), tiles[0][1].get_y_size()
    cols = 3
    rows = (len(tiles) + cols - 1) // cols
    sheet = PNMImage(w * cols + 8 * (cols - 1), h * rows + 8 * (rows - 1))
    sheet.fill(1, 1, 1)
    for i, (name, img) in enumerate(tiles):
        sheet.copy_sub_image(img, (i % cols) * (w + 8), (i // cols) * (h + 8))
        print(f"tile {i}: {name} eye={EYES[name]}")
    sheet.write(Filename.from_os_specific(args.out))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
