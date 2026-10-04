"""Make a Sketchfab/glTF-Transform GLB loadable by panda3d-gltf.

Built for "Mech bust" (Just8), and general for the same failure modes:

  1. EXT_meshopt_compression / KHR_mesh_quantization -- panda3d-gltf cannot
     decode either. NOT handled here (no Python decoder); unpack first with
     Node's glTF-Transform:
         npx -y @gltf-transform/cli@4 dequantize in.glb unpacked.glb
  2. EXT_texture_webp -- Panda3D cannot read WebP. Re-encoded: JPEG q90 for
     opaque images, PNG where alpha is really used. (gltf-transform's own
     `png` command silently did nothing without its image library.)
  3. Several skins sharing one skeleton root -- panda3d-gltf builds one
     Character per ROOT, keeps the last skin, and raises KeyError on the
     rest. When skin i's inverse bind matrices are skin 0's times a constant
     M_i (checked), M_i is baked into the mesh and the mesh moved to skin 0.
  4. Skinned meshes beside, not under, the skeleton -- the Actor keeps only
     the Character's subtree and loaded zero meshes. Bones and meshes are
     regrouped under one new "Armature" node (skinned meshes ignore their
     own node transform, glTF 2.0 spec, so nothing moves).

  .venv/bin/python -m tools.fix_sketchfab_glb unpacked.glb fixed.glb
  npx -y @gltf-transform/cli@4 prune fixed.glb final.glb     # drop orphans

Needs Pillow (`pip install pillow`) and numpy.
"""
import io
import json
import struct
import sys

import numpy as np


def read_glb(path):
    b = open(path, "rb").read()
    jlen = struct.unpack("<I", b[12:16])[0]
    j = json.loads(b[20:20 + jlen])
    o = 20 + jlen
    blen = struct.unpack("<I", b[o:o + 4])[0]
    return j, bytearray(b[o + 8:o + 8 + blen])


def write_glb(path, j, binary):
    while len(binary) % 4:
        binary.append(0)
    j["buffers"][0]["byteLength"] = len(binary)
    js = json.dumps(j, separators=(",", ":")).encode()
    js += b" " * ((4 - len(js) % 4) % 4)
    with open(path, "wb") as f:
        f.write(struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(js) + 8 + len(binary)))
        f.write(struct.pack("<I4s", len(js), b"JSON"))
        f.write(js)
        f.write(struct.pack("<I4s", len(binary), b"BIN\x00"))
        f.write(binary)


def _append(j, binary, data):
    while len(binary) % 4:
        binary.append(0)
    j["bufferViews"].append({"buffer": 0, "byteOffset": len(binary),
                             "byteLength": len(data)})
    binary.extend(data)
    return len(j["bufferViews"]) - 1


def reencode_images(j, binary):
    from PIL import Image
    for img in j.get("images", []):
        if "bufferView" not in img:
            continue
        v = j["bufferViews"][img["bufferView"]]
        s = v.get("byteOffset", 0)
        im = Image.open(io.BytesIO(bytes(binary[s:s + v["byteLength"]])))
        if img.get("mimeType") in ("image/jpeg", "image/png") and im.format != "WEBP":
            continue
        out = io.BytesIO()
        if im.mode in ("RGBA", "LA") and im.getchannel("A").getextrema()[0] < 255:
            im.save(out, "PNG", optimize=True)
            img["mimeType"] = "image/png"
        else:
            im.convert("RGB").save(out, "JPEG", quality=90)
            img["mimeType"] = "image/jpeg"
        img["bufferView"] = _append(j, binary, out.getvalue())
    for tex in j.get("textures", []):
        ext = tex.get("extensions", {}).pop("EXT_texture_webp", None)
        if ext is not None:
            tex["source"] = ext["source"]
        if tex.get("extensions") == {}:
            del tex["extensions"]
    for key in ("extensionsUsed", "extensionsRequired"):
        if key in j:
            j[key] = [e for e in j[key] if e != "EXT_texture_webp"]
            if not j[key]:
                del j[key]


def _matrices(j, binary, accessor):
    a = j["accessors"][accessor]
    v = j["bufferViews"][a["bufferView"]]
    s = v.get("byteOffset", 0) + a.get("byteOffset", 0)
    raw = bytes(binary[s:s + a["count"] * 64])
    return np.frombuffer(raw, "<f4").reshape(-1, 4, 4).transpose(0, 2, 1)


def merge_skins(j, binary):
    skins = j.get("skins", [])
    if len(skins) < 2:
        return
    roots = {s.get("skeleton") for s in skins}
    joints = {tuple(s["joints"]) for s in skins}
    if len(roots) != 1 or len(joints) != 1:
        print("skins differ in root or joints; leaving them alone")
        return
    base = _matrices(j, binary, skins[0]["inverseBindMatrices"])
    for node in j["nodes"]:
        si = node.get("skin")
        if not si:
            continue
        other = _matrices(j, binary, skins[si]["inverseBindMatrices"])
        m = np.linalg.inv(base[0]) @ other[0]
        dev = max(np.abs(np.linalg.inv(base[k]) @ other[k] - m).max()
                  for k in range(len(base)))
        if dev > 1e-5:
            raise SystemExit(f"skin {si} is not a constant offset of skin 0 ({dev:g})")
        lin = m[:3, :3]
        if not np.allclose(lin, np.eye(3) * lin[0, 0], atol=1e-4) or lin[0, 0] <= 0:
            raise SystemExit(f"skin {si}'s offset is not a uniform scale; normals would need fixing")
        for prim in j["meshes"][node["mesh"]]["primitives"]:
            a = j["accessors"][prim["attributes"]["POSITION"]]
            v = j["bufferViews"][a["bufferView"]]
            if a["componentType"] != 5126 or a["type"] != "VEC3":
                raise SystemExit("positions are quantized: run gltf-transform dequantize first")
            s = v.get("byteOffset", 0) + a.get("byteOffset", 0)
            stride = v.get("byteStride", 12)
            pts = np.array([np.frombuffer(bytes(binary[s + k * stride:s + k * stride + 12]), "<f4")
                            for k in range(a["count"])], dtype=np.float64)
            pts = (pts @ lin.T + m[:3, 3]).astype("<f4")
            for k in range(a["count"]):
                binary[s + k * stride:s + k * stride + 12] = pts[k].tobytes()
            a["min"], a["max"] = pts.min(0).tolist(), pts.max(0).tolist()
        node["skin"] = 0
        print(f"mesh node {node.get('name')}: skin {si} -> 0 (scale {lin[0, 0]:.4f})")


def group_armature(j):
    scene = j["scenes"][j.get("scene", 0)]
    skin_nodes = [i for i, n in enumerate(j["nodes"]) if "skin" in n]
    if not skin_nodes or "skins" not in j:
        return
    root = j["skins"][0].get("skeleton")
    loose = [n for n in [root] + skin_nodes if n in scene["nodes"]]
    if root not in scene["nodes"] or len(loose) < 2:
        return
    j["nodes"].append({"name": "Armature", "children": loose})
    arm = len(j["nodes"]) - 1
    scene["nodes"] = [n for n in scene["nodes"] if n not in loose] + [arm]
    for s in j["skins"]:
        s["skeleton"] = arm
    print(f"grouped skeleton root and {len(loose) - 1} meshes under Armature")


def main(src, dst):
    j, binary = read_glb(src)
    blocked = {"EXT_meshopt_compression", "KHR_mesh_quantization"} & set(j.get("extensionsUsed", []))
    if blocked:
        raise SystemExit(f"{sorted(blocked)} present: run `npx -y @gltf-transform/cli@4 "
                         f"dequantize {src} unpacked.glb` first")
    reencode_images(j, binary)
    merge_skins(j, binary)
    group_armature(j)
    write_glb(dst, j, binary)
    print(f"wrote {dst}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    main(sys.argv[1], sys.argv[2])
