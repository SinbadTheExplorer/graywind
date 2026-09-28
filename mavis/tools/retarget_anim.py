"""Blender headless: retarget Mixamo clips onto the Keanu rig and export a GLB.

Run with Blender, not the project venv:

    /Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup \
        --python mavis/tools/retarget_anim.py -- \
        <keanu.fbx> <texture-dir> <out.glb> idle=<Breathing Idle.fbx> smoking=<Smoking.fbx> \
        dismiss=<Dismissing Gesture.fbx> angry=<Angry.fbx> stance=<Offensive Idle.fbx>

The model ships with **no animation at all** -- a game rip gives you the mesh
and the skeleton in its authoring bind pose, arms out at 45 degrees. That pose
is most of why the avatar read as a mannequin, and no amount of procedural
head-drift on top of it helps.

**How the retarget works, and why the obvious way fails.** Each bone's rotation
is transferred as a *world-space* delta from its own rest pose:

    tgt_rot = (src_rot @ src_rest^-1) @ tgt_rest

At rest that is the identity. Because the delta is expressed in world space
rather than in either skeleton's local bone frame, it survives Mixamo and
ValveBiped having entirely different bone rolls and axis conventions. The
tempting alternative -- copying local rotations -- assumes the two rigs agree
on what "bend forward" means per bone, and produces arms rotated into the
torso.

Bones are posed parents-first so a child's world matrix is computed against a
parent already in its final pose.

**Rotation only -- the clips are treated as in-place.** This file used to carry
hip travel as well, scaled by the two rigs' height ratio, but it compared pose
bones with `is`, and bpy hands out a fresh wrapper on every access, so the
translation was never keyframed on any clip that ever shipped. Making it fire
sent the pelvis 18 metres across the room: the rigs sit at different unit
scales (the Mixamo armature carries a 0.01 object scale, this one does not) and
a height ratio does not reconcile that. Every clip used here is in-place, so
the travel bought nothing; re-deriving it properly is only worth it if a clip
that actually walks is ever retargeted.

Only the 22 body bones below are driven. The 283 CDPR facial joints are left
alone deliberately: `mid_J_jaw_JNT` stays free for lipsync to control, and
Mixamo has nothing to say about a face anyway.
"""
import os
import sys

import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fbx_to_glb as conv  # noqa: E402

TARGET_HEIGHT = 1.8

# Every clip is baked onto one 30fps timeline. Mixamo ships some clips at 30
# and some at 60, and the FBX importer silently sets the SCENE rate to that of
# whichever file it read last -- the exporter then times every clip against
# it. Importing Angry (60fps) after Smoking (30) halved Smoking's duration.
OUT_FPS = 30

M = "mixamorig:"
V = "ValveBiped.Bip01_"

BONE_MAP = {
    M + "Hips": V + "Pelvis",
    M + "Spine": V + "Spine",
    M + "Spine1": V + "Spine1",
    M + "Spine2": V + "Spine2",
    M + "Neck": V + "Neck1",
    M + "Head": V + "Head1",
    M + "LeftShoulder": V + "L_Clavicle",
    M + "LeftArm": V + "L_UpperArm",
    M + "LeftForeArm": V + "L_Forearm",
    M + "LeftHand": V + "L_Hand",
    M + "RightShoulder": V + "R_Clavicle",
    M + "RightArm": V + "R_UpperArm",
    M + "RightForeArm": V + "R_Forearm",
    M + "RightHand": V + "R_Hand",
    M + "LeftUpLeg": V + "L_Thigh",
    M + "LeftLeg": V + "L_Calf",
    M + "LeftFoot": V + "L_Foot",
    M + "LeftToeBase": V + "L_Toe0",
    M + "RightUpLeg": V + "R_Thigh",
    M + "RightLeg": V + "R_Calf",
    M + "RightFoot": V + "R_Foot",
    M + "RightToeBase": V + "R_Toe0",
}
ROOT_SRC = M + "Hips"
Y_AXIS = Vector((0.0, 1.0, 0.0))    # a Blender bone points down its own Y
REST_ALIGNED = {M + side + part for side in ("Left", "Right")
                for part in ("Shoulder", "Arm", "ForeArm", "Hand")}


def _depth(bone):
    count = 0
    while bone.parent:
        bone = bone.parent
        count += 1
    return count


def retarget(target, anim_fbx, action_name):
    """Bake one clip onto `target`, returning the new action."""
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=anim_fbx)
    imported = [o for o in bpy.data.objects if o not in before]
    source = next(o for o in imported if o.type == "ARMATURE")

    # Bake the clip's own length, not the scene's. The factory scene is always
    # frames 1-250, which silently cut Smoking (538) to under half, clipped
    # Breathing Idle (299) so its loop popped at the seam, and padded the
    # 68-frame Dismissing Gesture with six seconds of frozen hold.
    scene = bpy.context.scene
    src_action = source.animation_data.action
    start, end = (int(round(f)) for f in src_action.frame_range)
    scene.frame_start, scene.frame_end = start, end
    # Read straight after the import, which is what sets it: the clip's own rate.
    src_fps = scene.render.fps / scene.render.fps_base
    step = src_fps / OUT_FPS
    out_frames = int(round((end - start) / step)) + 1

    pairs = [(source.pose.bones[s], target.pose.bones[t])
             for s, t in BONE_MAP.items()
             if s in source.pose.bones and t in target.pose.bones]
    print(f"  mapped {len(pairs)}/{len(BONE_MAP)} bones")

    # The two rigs do not share a rest pose: Mixamo rests in a T-pose, this
    # model in an A-pose with the forearms bent forward -- upper arms 52 deg
    # apart, forearms 67. A delta taken from one rest and applied to the other
    # carries that gap into every frame, which flared the elbows and folded the
    # forearms across the stomach. So first swing each target rest bone to
    # point where its source bone points, and transfer deltas from there.
    # Only the arm chain: spine, neck and head stand upright in both rests,
    # but their bone axes point differently, and aligning those threw the
    # head all the way back.
    #
    # All of it in WORLD space. The two FBX imports leave the armature objects
    # rotated 90 deg apart, so bone matrices (armature space) from one rig mean
    # something else in the other; mixing them rotated every delta's axis.
    src_world = source.matrix_world.to_quaternion().to_matrix()
    tgt_world = target.matrix_world.to_quaternion().to_matrix()
    tgt_world_inv = tgt_world.inverted()
    correction = {}
    for s, t in pairs:
        src_rest = src_world @ s.bone.matrix_local.to_3x3()
        tgt_rest = tgt_world @ t.bone.matrix_local.to_3x3()
        swing = (tgt_rest @ Y_AXIS).rotation_difference(src_rest @ Y_AXIS).to_matrix() \
            if s.name in REST_ALIGNED else Matrix.Identity(3)
        correction[t.name] = (src_rest.inverted(), swing @ tgt_rest)

    pairs.sort(key=lambda p: _depth(p[1].bone))

    target.animation_data_create()
    action = bpy.data.actions.new(action_name)
    target.animation_data.action = action
    for pose_bone in target.pose.bones:
        pose_bone.rotation_mode = "QUATERNION"

    for i in range(out_frames):
        src_frame = start + i * step
        scene.frame_set(int(src_frame), subframe=src_frame % 1.0)
        frame = start + i
        for s, t in pairs:
            src_inv, tgt_rest = correction[t.name]
            world = (src_world @ s.matrix.to_3x3() @ src_inv) @ tgt_rest
            matrix = (tgt_world_inv @ world).to_4x4()
            matrix.translation = t.matrix.translation
            t.matrix = matrix
            bpy.context.view_layer.update()
        for _s, t in pairs:
            t.keyframe_insert("rotation_quaternion", frame=frame)

    print(f"  baked {out_frames} frames as {action_name!r} "
          f"(source {end - start + 1} @ {src_fps:g}fps)")

    # Names first: removing an object dangles every other reference to it.
    for name in [o.name for o in imported]:
        obj = bpy.data.objects.get(name)
        if obj is not None:
            bpy.data.objects.remove(obj, do_unlink=True)

    target.animation_data.action = None
    return action


def main():
    argv = sys.argv[sys.argv.index("--") + 1:]
    target_fbx, texdir, out_glb = argv[0], argv[1], argv[2]
    clips = [spec.split("=", 1) for spec in argv[3:]]
    if not clips:
        raise SystemExit("give at least one clip as name=path/to/clip.fbx")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=target_fbx, automatic_bone_orientation=True)
    target = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    target.name = "Johnny"

    ours = []
    for name, path in clips:
        print(f"CLIP {name} <- {os.path.basename(path)}")
        ours.append(retarget(target, path, name))

    # Purge every action we did not create. Importing a clip brings its own
    # Mixamo action along, and those survive deleting the object that used
    # them -- they would otherwise be exported beside ours as a second,
    # meaningless animation on the finished model.
    keep = {action.name for action in ours}
    for action in list(bpy.data.actions):
        if action.name not in keep:
            print(f"  purged stray action {action.name!r}")
            bpy.data.actions.remove(action)

    # One NLA track per clip is what makes the glTF exporter emit each as its
    # own named animation rather than exporting only the active action.
    target.animation_data.action = None
    for action in ours:
        track = target.animation_data.nla_tracks.new()
        track.name = action.name
        track.strips.new(action.name, int(action.frame_range[0]), action)

    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    for obj in meshes:
        obj.data.name = obj.name
    conv.wire_materials(texdir)

    low = Vector((1e9,) * 3)
    high = Vector((-1e9,) * 3)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    for obj in meshes:
        for corner in obj.evaluated_get(depsgraph).bound_box:
            world = obj.matrix_world @ Vector(corner)
            low = Vector((min(low[i], world[i]) for i in range(3)))
            high = Vector((max(high[i], world[i]) for i in range(3)))
    height = high[2] - low[2]
    factor = TARGET_HEIGHT / height
    target.scale = tuple(value * factor for value in target.scale)
    print(f"SCALED {height:.2f} -> {TARGET_HEIGHT} (factor {factor:.5f})")

    scene = bpy.context.scene
    scene.render.fps, scene.render.fps_base = OUT_FPS, 1.0
    bpy.ops.export_scene.gltf(
        filepath=out_glb, export_format="GLB", export_skins=True,
        export_yup=True, export_animations=True, export_apply=False,
    )
    print(f"EXPORTED {out_glb} with {len(ours)} animation(s): "
          f"{', '.join(sorted(keep))}")


if __name__ == "__main__":
    main()
