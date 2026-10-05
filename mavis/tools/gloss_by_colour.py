"""Make part of a material mirror-like, chosen by its painted colour.

Visors, glass and chrome trim are often painted into one big texture with the
rest of the armour, so there is no separate mesh or material to make shiny.
This finds those pixels by colour in the material's base-colour map and, in a
COPY of its packed metal/roughness map, makes them metallic and smooth -- a
metal reflects the room TINTED by its own colour, which is what a gold visor
is. Everything else keeps its own values; the mask edges are feathered so the
change has no visible seam.

Written for the Spartan's visor: its occlusion/roughness/metal map already
called the visor smooth but NON-metal, so it reflected ~4% untinted light and
read as matte orange plastic.

  .venv/bin/python -m tools.gloss_by_colour in.glb out.glb \\
      --material Spartan_Helmet_Mat --hue 20 55 --min-sat 0.45 --min-val 0.2 \\
      --roughness 0.12 --metal 1.0 --preview mask.png

glTF packs roughness in G and metalness in B; R (occlusion, when the map is
shared) is left alone.
"""
import argparse
import io
import sys

import numpy as np


def colour_mask(rgb: np.ndarray, hue, min_sat: float, min_val: float,
                feather_px: int = 3) -> np.ndarray:
    """0..1 mask of pixels whose HSV falls in range, edges feathered."""
    from PIL import Image, ImageFilter
    x = rgb.astype(np.float32) / 255.0
    mx, mn = x.max(-1), x.min(-1)
    val = mx
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0.0)
    r, g, b = x[..., 0], x[..., 1], x[..., 2]
    d = np.maximum(mx - mn, 1e-6)
    h = np.where(mx == r, ((g - b) / d) % 6,
                 np.where(mx == g, (b - r) / d + 2, (r - g) / d + 4)) * 60.0
    lo, hi = hue
    m = ((h >= lo) & (h <= hi) & (sat >= min_sat) & (val >= min_val)).astype(np.uint8) * 255
    img = Image.fromarray(m, "L")
    if feather_px:
        img = img.filter(ImageFilter.GaussianBlur(feather_px))
    return np.asarray(img).astype(np.float32) / 255.0


def main(argv=None) -> int:
    from PIL import Image
    sys.path.insert(0, ".")
    from tools.fix_sketchfab_glb import _append, read_glb, write_glb

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--material", required=True)
    ap.add_argument("--hue", type=float, nargs=2, required=True, metavar=("LO", "HI"))
    ap.add_argument("--min-sat", type=float, default=0.4)
    ap.add_argument("--min-val", type=float, default=0.15)
    ap.add_argument("--roughness", type=float, default=0.12)
    ap.add_argument("--metal", type=float, default=1.0)
    ap.add_argument("--preview", help="write the mask here to check it")
    a = ap.parse_args(argv)

    j, binary = read_glb(a.src)

    def image(tex_index):
        src = j["textures"][tex_index]["source"]
        v = j["bufferViews"][j["images"][src]["bufferView"]]
        s = v.get("byteOffset", 0)
        return Image.open(io.BytesIO(bytes(binary[s:s + v["byteLength"]])))

    mats = [m for m in j["materials"] if m.get("name") == a.material]
    if not mats:
        raise SystemExit(f"no material {a.material!r}; have "
                         f"{[m.get('name') for m in j['materials']]}")
    mat = mats[0]
    pbr = mat.setdefault("pbrMetallicRoughness", {})
    if "baseColorTexture" not in pbr or "metallicRoughnessTexture" not in pbr:
        raise SystemExit("material needs both a base-colour and a metal/roughness map")

    base = np.asarray(image(pbr["baseColorTexture"]["index"]).convert("RGB"))
    mr_index = pbr["metallicRoughnessTexture"]["index"]
    mr = np.asarray(image(mr_index).convert("RGB")).astype(np.float32)
    if mr.shape[:2] != base.shape[:2]:
        base = np.asarray(Image.fromarray(base).resize(mr.shape[1::-1], Image.LANCZOS))
    mask = colour_mask(base, a.hue, a.min_sat, a.min_val)
    print(f"mask covers {mask.mean() * 100:.1f}% of the texture")
    if a.preview:
        Image.fromarray((mask * 255).astype(np.uint8), "L").save(a.preview)

    mr[..., 1] = mr[..., 1] * (1 - mask) + a.roughness * 255 * mask
    mr[..., 2] = mr[..., 2] * (1 - mask) + a.metal * 255 * mask
    out = io.BytesIO()
    Image.fromarray(np.clip(mr + 0.5, 0, 255).astype(np.uint8), "RGB").save(out, "PNG", optimize=True)

    # A NEW image + texture, so other materials sharing the old map keep it.
    view = _append(j, binary, out.getvalue())
    j["images"].append({"bufferView": view, "mimeType": "image/png",
                        "name": f"{a.material}_gloss"})
    tex = dict(j["textures"][mr_index], source=len(j["images"]) - 1)
    j["textures"].append(tex)
    new_index = len(j["textures"]) - 1
    pbr["metallicRoughnessTexture"]["index"] = new_index
    if mat.get("occlusionTexture", {}).get("index") == mr_index:
        mat["occlusionTexture"]["index"] = new_index     # same packed map
    write_glb(a.dst, j, binary)
    print(f"wrote {a.dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
