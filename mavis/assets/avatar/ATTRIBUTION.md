# Avatar model attribution

`mech-bust` (committed, below) is the default; `keanu` is used when built
locally and chosen with M or `MAVIS_AVATAR=keanu`. The free Sketchfab "Jonny
Silverhand" (Stuxed, CC BY) was removed on 2026-10-04 at the owner's request. More can be
dropped in without code changes -- see "Adding your own models" at the end.
Press **M** while he runs to cycle through every model on disk.

**This directory is gitignored except for `ATTRIBUTION.md` and the
`extra/mech-bust/` model.**
The repo is public, so committing a model publishes it. Only add an unignore
line in `mavis/.gitignore` for an asset whose licence actually permits
redistribution, and record it here when you do.

---

## `keanu` — NOT committed, not redistributable

"Cyberpunk 2077 Johnny Silverhand 3D Model" ported by **KonnieGFX**
https://www.deviantart.com/konniegfx/art/Cyberpunk-2077-Johnny-Silverhand-3D-Model-864523437

**The character and mesh are © CD Projekt Red.** The uploader states plainly:
*"Model belongs to CD Projekt Red, I don't own the rights to this model, just
allowing people to use the 3D model."* No licence is granted by anyone with
standing to grant one, so this asset is **local-use only** — never commit it,
never publish a build containing it, and keep the on-screen credit. The
uploader also asks that it not be used for nudity or inappropriate content.

It is a port of the actual in-game character, rigged to a Valve `Bip01`
skeleton (a Garry's Mod port) carrying CDPR's facial joints. It has **no morph
targets at all** — Cyberpunk animates faces with joints, which is exactly why
the facial rig survived extraction. The mouth is therefore driven by rotating
`mid_J_jaw_JNT`; `r` is the axis that opens it, `h` and `p` skew the face
sideways.

### Animation

The model ships with **no animation** — a game rip gives you the mesh and the
skeleton in its bind pose, arms out at 45°, which is most of why it read as a
mannequin. Motion comes from **Mixamo** (Adobe, free with an Adobe ID, licensed
for use): `Breathing Idle`, `Smoking`, `Dismissing Gesture`, `Angry` and `Offensive Idle`, downloaded as FBX and retargeted onto
this model's ValveBiped skeleton by `tools/retarget_anim.py`.

Mixamo clips are not redistributed here either. Download them yourself from
mixamo.com (search the clip name, Format: FBX Binary) and point the tool at
them. "With Skin" is fine — only the armature is read.

### Rebuilding `keanu.bam`

Needs Blender (`brew install --cask blender`) — Panda3D cannot read FBX.
Download "Keanu 3D model.rar" from the DeviantArt page above and extract it,
then, from `mavis/`:

    # with animation (what ships):
    /Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup \
        --python tools/retarget_anim.py -- \
        "<extracted>/keanu.fbx" "<extracted>" /tmp/keanu.glb \
        "idle=<path>/Breathing Idle.fbx" "smoking=<path>/Smoking.fbx" \
        "dismiss=<path>/Dismissing Gesture.fbx" \
        "angry=<path>/Angry.fbx" "stance=<path>/Offensive Idle.fbx"
    .venv/bin/gltf2bam /tmp/keanu.glb assets/avatar/keanu.bam

    # without animation (fbx_to_glb.py is the same pipeline minus the clips):
    /Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup \
        --python tools/fbx_to_glb.py -- \
        "<extracted>/keanu.fbx" /tmp/keanu.glb "<extracted>" 1.8

`tools/fbx_to_glb.py` documents why each step is needed: the FBX references no
textures (they are matched to materials by filename), every mesh's *data* name
is junk so the exporter would name the nodes unusably, the model is ~73 units
tall, and the source textures are ~357MB of uncompressed 2048px TGAs. The
result is ~80MB; skipping the texture caps gives ~344MB instead, which matters
on the 8GB M2 this targets.

---

## `mech-bust` — committed, CC BY 4.0 (modified)

"Mech bust" by **Just8** — https://sketchfab.com/3d-models/mech-bust-f06084d487d94137bc4dd58e48696439
— the model in the off-axis-projection reel that portal mode was built from.

Licensed **CC Attribution 4.0** (stated in the file's own `asset.extras`).
The on-screen credit `Model: "Mech bust" by Just8 (CC BY 4.0)` is the
licence condition; do not remove it.

**Changes from the original** (CC BY requires saying so). The download is a
glTF-Transform–optimised GLB (meshopt geometry, quantized attributes, WebP
textures) that panda3d-gltf cannot read. `mech_bust.glb` here was produced by:

    npx -y @gltf-transform/cli@4 dequantize mech_bust_small.glb unpacked.glb
    .venv/bin/python -m tools.fix_sketchfab_glb unpacked.glb fixed.glb
    npx -y @gltf-transform/cli@4 prune fixed.glb mech_bust.glb

i.e. geometry decompressed; WebP textures re-encoded as JPEG (PNG where alpha
is used); four of its five skins, which share one skeleton and differ only by
a uniform scale + offset, merged into the first with that offset baked into
their vertices; bones and meshes regrouped under one `Armature` node; and
Sketchfab's background-particle plane dropped. Appearance and animation are
otherwise unchanged. 21.9 MB, 226k triangles, 54 bones, one clip (`anim`),
jaw `jaw_07` (hinge axis `r`) drives the mouth.

---

## Adding your own models (press M to cycle)

Any rigged character can join the rotation. Make a folder under
`assets/avatar/extra/` named for the model, put the model and an
`avatar.json` in it, and restart Johnny:

    assets/avatar/extra/robot/robot.glb
    assets/avatar/extra/robot/avatar.json

**Everything under `extra/` is gitignored** (it sits inside the ignored
`assets/avatar/*`), so a model you are allowed to *use* but not to
*redistribute* never reaches this public repo. Keep it that way.

Let the inspector write `avatar.json` for you, then fix the credit by hand:

    .venv/bin/python -m tools.inspect_model assets/avatar/extra/robot/robot.glb

| key | required | meaning |
|---|---|---|
| `model` | yes | file name inside the folder: `.glb`, `.gltf` or `.bam` |
| `credit` | yes | shown on screen. For CC BY models the credit IS the licence condition |
| `head_mesh` | no | mesh to frame on; without it the top `head_fraction` of the model is assumed to be the head |
| `head_fraction` | no | used only without `head_mesh`: 0.19 (default) for a full figure, ~0.5 for a bust, ~0.9 for a head alone |
| `mouth` | no | `{"kind": "slider", "slider": "jawOpen"}` (a morph), `{"kind": "joint", "joint": "...", "axis": "p", "degrees": 14}` (a jaw bone), `{"kind": "nod", "degrees": 3}` (the whole model dips with his voice), or omit for no lip-sync |
| `idle_anim` | no | clip to loop; without one he holds still and sways |
| `anims`, `idle_variety`, `poses`, `sway` | no | as in the built-in `keanu` entry in `avatar/scene.py` |

**Models with no skeleton work too** -- a static mesh, which is what most
mech/robot heads are. They load, sway, and nod along with his voice instead
of lip-syncing (any `mouth` setting is replaced by `nod` for them).

A folder with a broken or incomplete `avatar.json` is skipped with a printed
reason; it never stops Johnny from starting. A model that fails to *load*
when you press M puts the previous one back and says why on screen.

Where to find models, and what each licence lets you do:

- **Sketchfab** -- filter by *Downloadable* and an animated/rigged tag; download
  the glTF. CC BY needs the credit line; CC BY-NC is fine for this personal use.
- **Mixamo** (free Adobe account) -- characters and clips, royalty-free to use
  but not to redistribute as raw files. FBX only: convert with Blender as in
  "Rebuilding keanu.bam" above (`tools/fbx_to_glb.py`).
- **VRoid Hub** -- VRM avatars (a glTF variant); each author sets their own
  terms on the model's page. Not yet tried here -- `panda3d-gltf` may need the
  `.vrm` renamed to `.glb`, and may ignore VRM-specific extensions.

Model size matters on the 8GB M2: Panda3D keeps every model it has loaded
cached in memory, so cycling through several 80MB models adds up.

