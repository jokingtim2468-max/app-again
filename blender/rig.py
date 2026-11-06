"""Auto-rig a humanoid mesh with Rigify basic human metarig (deform bones only - game-engine friendly).
Usage: python blender/rig.py in.glb out.fbx|out.glb
Assumes: cleaned mesh (blender/cleanup.py), standing, facing -Y, origin at feet. Falls back to envelope
weights when automatic weights fail (non-manifold meshes).
"""
import sys, bpy, addon_utils

src, dst = sys.argv[-2], sys.argv[-1]
addon_utils.enable("rigify", default_set=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
addon_utils.enable("rigify", default_set=True)
(bpy.ops.import_scene.gltf if src.endswith((".glb", ".gltf")) else bpy.ops.import_scene.fbx)(filepath=src)
meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
zs = [(o.matrix_world @ v.co).z for o in meshes for v in o.data.vertices]
height = max(zs) - min(zs)

bpy.ops.object.armature_basic_human_metarig_add()  # ~30 bones: game-friendly (no face rig)
rig = bpy.context.active_object
rig.name = "Rig"
rig.scale = [height / rig.dimensions.z] * 3
bpy.ops.object.transform_apply(scale=True)

bpy.ops.object.select_all(action="DESELECT")
for m in meshes:
    m.select_set(True)
rig.select_set(True)
bpy.context.view_layer.objects.active = rig
try:
    bpy.ops.object.parent_set(type="ARMATURE_AUTO")
    mode = "auto"
except RuntimeError:
    bpy.ops.object.parent_set(type="ARMATURE_ENVELOPE")
    mode = "envelope"
groups = sum(len(m.vertex_groups) for m in meshes)
print(f"rigged height={height:.2f} bones={len(rig.data.bones)} weights={mode} vertex_groups={groups}")
if dst.endswith(".fbx"):
    bpy.ops.export_scene.fbx(filepath=dst, add_leaf_bones=False, bake_anim=False)
else:
    bpy.ops.export_scene.gltf(filepath=dst, export_format="GLB")
