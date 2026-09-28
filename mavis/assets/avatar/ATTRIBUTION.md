# Avatar model attribution

Two models are supported. `avatar/scene.py` picks `keanu` when it has been
built and falls back to `jonny`; `MAVIS_AVATAR=jonny|keanu` overrides.

**This directory is gitignored except for `ATTRIBUTION.md` and `jonny.glb`.**
The repo is public, so committing a model publishes it. Only add an unignore
line in `mavis/.gitignore` for an asset whose licence actually permits
redistribution, and record it here when you do.

---

## `jonny` — committed, CC BY

"Jonny Silverhand" by **Stuxed**
https://sketchfab.com/3d-models/jonny-silverhand-806032afcab34b118809e864a5c54ee4

Licensed **CC Attribution (CC BY)**. Credit is a licence condition, so the
on-screen credit in `avatar/scene.py` is required, not decorative. Do not
remove it.

A stylized fan interpretation, not screen-accurate — the creator notes the
metal arm is on the wrong side. The base mesh is a Ready Player Me export,
which is where the `Wolf3D_*` mesh names and the aliased UV sets come from.
Being an RPM export is also why it has `mouthOpen`/`mouthSmile` **morph
targets**, which is how its mouth moves.

All 20 textures are embedded in the GLB's binary chunk as `bufferView`
images — there are no external `uri` references, so `jonny.glb` is
self-contained and can be moved without breaking texture resolution.

`jonny.glb` is the Sketchfab "Original format" download and is the only model
file here under version control. Rebuild its artifacts with:

    .venv/bin/python -m tools.repair_gltf
    .venv/bin/gltf2bam assets/avatar/jonny_fixed.glb assets/avatar/jonny_fixed.bam

`gltf2bam` should print **no** `Could not find joint in jvtmap` warnings. An
earlier revision of the repair produced ~189 of them and they were recorded
here as harmless zero-weight joint indices. They were not harmless: they were
a symptom of `Wolf3D_Outfit_Bottom` being read at the wrong stride, which also
exploded that mesh to ±18 units and put the camera inside the geometry. If
those warnings ever come back, the repair is wrong again — see
`tools/repair_gltf.py` and `test_declared_attributes_fill_the_byte_stride`.

**This is the only model the test suite may assert against**, because it is
the only one present on a fresh clone.

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
