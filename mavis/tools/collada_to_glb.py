"""Turn a Sketchfab "source" download (COLLADA .dae + loose PBR textures) into a GLB.

Sketchfab's source zips for older uploads hold `model.dae` -- often written by
Assimp, with a plain Phong material that references none of the textures --
plus a folder of `<name>_albedo / _normal / _metallic / _roughness / _emissive
/ _AO` images. panda3d-gltf reads neither COLLADA nor loose textures, so this
rebuilds the model as glTF with those images wired into one PBR material:
metallic and roughness are packed into the single image glTF expects (G =
roughness, B = metalness). Textures are written as JPEG.

  .venv/bin/pip install trimesh pycollada pillow      # tool-only deps
  .venv/bin/python -m tools.collada_to_glb source/model/model.dae source/model/textures out.glb

Every mesh in the file gets the same material, which is how these exports are
laid out (one texture set). Anything missing from the texture folder is
simply left off the material.
"""
import io
import sys
from pathlib import Path

ROLES = {
    "baseColorTexture": "albedo",
    "normalTexture": "normal",
    "emissiveTexture": "emissive",
    "occlusionTexture": "ao",
}


def find_texture(folder: Path, role: str):
    for path in sorted(folder.iterdir()):
        if path.suffix.lower() in (".jpg", ".jpeg", ".png") and \
                path.stem.lower().endswith("_" + role):
            return path
    return None


def build_material(folder: Path):
    import trimesh
    from PIL import Image

    def load(role):
        path = find_texture(folder, role)
        return Image.open(path).convert("RGB") if path else None

    kwargs = {key: load(role) for key, role in ROLES.items()}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    metal = find_texture(folder, "metallic")
    rough = find_texture(folder, "roughness")
    if metal and rough:
        m = Image.open(metal).convert("L")
        r = Image.open(rough).convert("L").resize(m.size)
        kwargs["metallicRoughnessTexture"] = Image.merge(
            "RGB", (Image.new("L", m.size, 0), r, m))
        kwargs["metallicFactor"] = kwargs["roughnessFactor"] = 1.0
    if "emissiveTexture" in kwargs:
        kwargs["emissiveFactor"] = [1.0, 1.0, 1.0]
    print("textures:", sorted(kwargs))
    return trimesh.visual.material.PBRMaterial(name="model", **kwargs)


def main(dae: str, textures: str, out: str) -> None:
    import trimesh
    from PIL import Image

    material = build_material(Path(textures))
    scene = trimesh.load(dae, force="scene")
    for name, geom in scene.geometry.items():
        uv = getattr(geom.visual, "uv", None)
        if uv is None:
            print(f"warning: {name} has no UVs; it will render untextured")
            continue
        geom.visual = trimesh.visual.TextureVisuals(uv=uv, material=material)
    scene.export(out)

    # trimesh writes PNG; re-encode opaque images as JPEG (17MB -> 3MB on the
    # first model this was used for).
    from tools.fix_sketchfab_glb import _append, read_glb, write_glb
    j, binary = read_glb(out)
    for img in j.get("images", []):
        v = j["bufferViews"][img["bufferView"]]
        s = v.get("byteOffset", 0)
        im = Image.open(io.BytesIO(bytes(binary[s:s + v["byteLength"]])))
        buf = io.BytesIO()
        im.convert("RGB").save(buf, "JPEG", quality=90)
        img["bufferView"] = _append(j, binary, buf.getvalue())
        img["mimeType"] = "image/jpeg"
    write_glb(out, j, binary)
    print(f"wrote {out} (run `npx -y @gltf-transform/cli@4 prune` on it to "
          "drop the replaced PNG bytes)")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(2)
    main(*sys.argv[1:])
