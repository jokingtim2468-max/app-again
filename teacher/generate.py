"""Teacher: Qwen3.5-122B-A10B (Apache-2.0) writes prompts, then answers each N times.
Runs on one 80 GB GPU (A100/H100) with vLLM. Output: teacher_raw.jsonl
  {"id","engine","topic","level","prompt","candidates":[str,...]}
Checking/filtering happens later (teacher/ingest.py) - this script only generates.
"""
import argparse, json, random, re
from vllm import LLM, SamplingParams

p = argparse.ArgumentParser()
p.add_argument("--model", default="Qwen/Qwen3.5-122B-A10B-GPTQ-Int4")
p.add_argument("--per-group", type=int, default=25, help="prompts per engine x topic x level")
p.add_argument("--samples", type=int, default=4, help="answers per prompt")
p.add_argument("--out", default="teacher_raw.jsonl")
p.add_argument("--max-len", type=int, default=8192)
a = p.parse_args()

TOPICS = ["main/pause/settings menus", "HUD and health/stamina bars", "inventory and item UI", "shop and economy",
          "procedural map and terrain generation", "level layout, obstacles and checkpoints", "player character movement and camera",
          "NPC and enemy AI", "combat, damage and hitboxes", "saving and loading player data", "quests and dialogue",
          "leaderboards and stats", "multiplayer networking and anti-cheat validation", "audio and music managers",
          "particles, VFX and tweening", "tutorial and onboarding flow", "object pooling and performance", "game state and round systems"]
ENGINES = {
    "roblox": ("Roblox Luau", "Write ONE complete Luau script with --!strict at the top. Say in a first-line comment whether it is a Script, "
               "LocalScript or ModuleScript and where it goes. Use only built-in Roblox services. Never trust the client: validate on the server."),
    "unity": ("Unity C#", "Write ONE complete, self-contained C# file for Unity 2021.3+. Use only UnityEngine, UnityEngine.UIElements (UI Toolkit), "
              "UnityEngine.AI, UnityEngine.SceneManagement, UnityEngine.Tilemaps and System namespaces. Do NOT use TextMeshPro, "
              "UnityEngine.UI (uGUI), the new Input System package, or classes defined in other files. C# 9 max."),
}
LEVELS = ["beginner", "intermediate", "advanced"]

llm = LLM(model=a.model, max_model_len=a.max_len, gpu_memory_utilization=0.92, trust_remote_code=True)
NO_THINK = {"enable_thinking": False}

# ---- stage 1: teacher writes the prompts
groups, convs = [], []
for eng, (name, _) in ENGINES.items():
    for topic in TOPICS:
        for lvl in LEVELS:
            groups.append((eng, topic, lvl))
            convs.append([{"role": "user", "content":
                f"List {a.per_group} distinct, specific requests a {lvl} game developer would ask an AI assistant about "
                f"'{topic}' in {name}. Vary genres (obby, tycoon, RPG, shooter, racing, survival, puzzle, platformer), "
                f"art styles and concrete numbers. Each request must be answerable with a single code file. "
                f"Return ONLY a JSON array of strings."}])
outs = llm.chat(convs, SamplingParams(temperature=0.9, top_p=0.95, max_tokens=4096), chat_template_kwargs=NO_THINK)
tasks, seen = [], set()
for (eng, topic, lvl), o in zip(groups, outs):
    m = re.search(r"\[.*\]", o.outputs[0].text, re.S)
    try:
        items = json.loads(m.group(0)) if m else []
    except json.JSONDecodeError:
        items = []
    for t in items:
        if isinstance(t, str) and 20 < len(t) < 600 and t.lower() not in seen:
            seen.add(t.lower())
            tasks.append({"id": f"t{len(tasks)}", "engine": eng, "topic": topic, "level": lvl, "prompt": t})
print(f"stage 1: {len(tasks)} prompts from {len(groups)} groups")

# ---- stage 2: teacher answers each prompt N times
SYS = "You are an expert game developer. Reply with a short plan, then the code in one fenced block, then a brief explanation."
convs = [[{"role": "system", "content": SYS + " " + ENGINES[t["engine"]][1]}, {"role": "user", "content": t["prompt"]}] for t in tasks]
outs = llm.chat(convs, SamplingParams(n=a.samples, temperature=0.7, top_p=0.95, max_tokens=3072), chat_template_kwargs=NO_THINK)
with open(a.out, "w") as f:
    for t, o in zip(tasks, outs):
        t["candidates"] = [c.text for c in o.outputs]
        f.write(json.dumps(t) + "\n")
print(f"stage 2: wrote {len(tasks)} prompts x {a.samples} answers -> {a.out}")
