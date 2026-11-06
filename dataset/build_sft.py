"""Convert data/verified/verified.jsonl -> data/sft.jsonl (chat messages format)."""
import json, pathlib, random

ROOT = pathlib.Path(__file__).resolve().parents[1]
SYSTEM = ("You are a game-dev coding assistant for Roblox (Luau) and Unity (C#). "
          "Write correct, typed, production-ready code.")

rows = [json.loads(l) for l in (ROOT / "data/verified/verified.jsonl").read_text().splitlines()]
random.Random(0).shuffle(rows)
fence = {"luau": "lua", "csharp": "csharp"}
with open(ROOT / "data/sft.jsonl", "w") as f:
    for r in rows:
        f.write(json.dumps({"messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": r["prompt"]},
            {"role": "assistant", "content": f"```{fence[r['lang']]}\n{r['code']}\n```"},
        ]}) + "\n")
print(f"wrote {len(rows)} examples")
