"""Template-generated image-to-3D tool-call traces (no teacher model needed).

Workflow taught: generate one image per required angle -> TRELLIS.2 on front view (others kept as
reference) -> Blender bpy cleanup (fill holes, decimate, pivot, scale) -> engine import.
Output: data/traces_3d.jsonl in chat format with tool calls.
"""
import json, pathlib, random

ROOT = pathlib.Path(__file__).resolve().parents[1]
rng = random.Random(7)
OBJECTS = [("wooden treasure chest", 1.0), ("sci-fi crate", 1.2), ("low-poly pine tree", 6.0), ("stone well", 2.0),
           ("medieval sword", 1.1), ("street lamp", 4.0), ("cartoon mushroom", 0.8), ("office chair", 1.1),
           ("robot companion", 1.6), ("market stall", 3.0), ("potion bottle", 0.4), ("wooden barrel", 1.2),
           ("campfire", 0.6), ("space helmet", 0.5), ("park bench", 1.0), ("fantasy shield", 1.0),
           ("vending machine", 2.0), ("tombstone", 1.2), ("racing car", 1.5), ("cactus", 2.5)]
TARGETS = {"roblox": {"faces": 10000, "unit": "studs", "scale": 3.57, "fmt": "fbx"},
           "unity": {"faces": 20000, "unit": "meters", "scale": 1.0, "fmt": "glb"}}
ANGLES = ["front", "back", "left", "right", "top", "three_quarter"]
TOOLS = [
    {"name": "generate_view_images", "parameters": {"prompt": "str", "angles": "list[str]"}},
    {"name": "image_to_3d", "parameters": {"image": "str", "model": "TRELLIS.2-4B", "remove_bg": "BiRefNet"}},
    {"name": "blender_cleanup", "parameters": {"src": "str", "dst": "str", "faces": "int", "height": "float"}},
    {"name": "engine_import", "parameters": {"engine": "roblox|unity", "path": "str"}},
]


def call(name, **args):
    return {"role": "assistant", "content": "", "tool_calls": [{"type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}


def tool(name, content):
    return {"role": "tool", "name": name, "content": json.dumps(content)}


out = []
for obj, h in OBJECTS:
    for eng, t in TARGETS.items():
        slug = obj.replace(" ", "_")
        height = round(h * t["scale"], 2)
        n = rng.randint(150_000, 800_000)
        user = rng.choice([f"Make me a {obj} for my {eng.title()} game.",
                           f"I need a game-ready {obj} model in {eng.title()}.",
                           f"Turn this into a {eng.title()} asset: a {obj}."])
        msgs = [{"role": "system", "content": "You are a game-dev assistant. Tools: " + json.dumps(TOOLS)},
                {"role": "user", "content": user},
                {"role": "assistant", "content": f"Plan: generate {len(ANGLES)} reference views of the {obj}, convert the front view with TRELLIS.2, clean it up in Blender to {t['faces']} faces at {height} {t['unit']} tall, then import into {eng.title()}."},
                call("generate_view_images", prompt=f"{obj}, game asset, neutral background, even lighting", angles=ANGLES),
                tool("generate_view_images", {a: f"views/{slug}_{a}.png" for a in ANGLES}),
                call("image_to_3d", image=f"views/{slug}_front.png", model="TRELLIS.2-4B", remove_bg="BiRefNet"),
                tool("image_to_3d", {"mesh": f"raw/{slug}.glb", "faces": n, "note": "may contain small holes"}),
                call("blender_cleanup", src=f"raw/{slug}.glb", dst=f"clean/{slug}.{t['fmt']}", faces=t["faces"], height=height),
                tool("blender_cleanup", {"faces_before": n, "faces_after": t["faces"], "height": height, "pivot": "bottom-center"}),
                call("engine_import", engine=eng, path=f"clean/{slug}.{t['fmt']}"),
                tool("engine_import", {"ok": True}),
                {"role": "assistant", "content": f"Done. The {obj} is in {eng.title()}: {t['faces']:,} faces (from {n:,}), {height} {t['unit']} tall, pivot at the bottom center. Compare it with the back/side reference views and tell me if anything needs a fix."}]
        out.append({"messages": msgs, "source": "hand-written"})
(ROOT / "data/traces_3d.jsonl").write_text("\n".join(json.dumps(r) for r in out) + "\n")
print(len(out), "traces")
