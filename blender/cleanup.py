"""bpy cleanup for image-to-3D (TRELLIS.2) output.
Usage: python blender/cleanup.py in.glb out.glb [--faces 20000] [--height 1.0]
Steps: import -> merge doubles -> fill holes (Mac port skips hole filling) -> decimate ->
       origin to bottom-center -> scale to height -> apply transforms -> export GLB.
"""
import argparse, bpy

p = argparse.ArgumentParser()
p.add_argument("src"); p.add_argument("dst")
p.add_argument("--faces", type=int, default=20000)
p.add_argument("--height", type=float, default=1.0)
a = p.parse_args()

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=a.src)
meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
for ob in meshes:
    bpy.context.view_layer.objects.active = ob
    ob.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.remove_doubles(threshold=1e-4)
    bpy.ops.mesh.fill_holes(sides=32)
    bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode="OBJECT")
    n = len(ob.data.polygons)
    if n > a.faces:
        m = ob.modifiers.new("dec", "DECIMATE"); m.ratio = a.faces / n
        bpy.ops.object.modifier_apply(modifier=m.name)
    zs = [(ob.matrix_world @ v.co).z for v in ob.data.vertices]
    h = max(zs) - min(zs)
    if h > 0:
        ob.scale = [s * a.height / h for s in ob.scale]
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    bpy.ops.object.origin_set(type="ORIGIN_GEOMETRY", center="BOUNDS")
    ob.location.z -= min((ob.matrix_world @ v.co).z for v in ob.data.vertices) - ob.location.z
    print(f"{ob.name}: {n} -> {len(ob.data.polygons)} faces")
bpy.ops.export_scene.gltf(filepath=a.dst, export_format="GLB")
