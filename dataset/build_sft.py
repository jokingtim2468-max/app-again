"""verified.jsonl + traces_3d.jsonl -> data/sft.jsonl (train) + data/eval.jsonl (5% held out)."""
import json, pathlib, random

ROOT = pathlib.Path(__file__).resolve().parents[1]
SYSTEM = ("You are a game-dev coding assistant for Roblox (Luau) and Unity (C#). "
          "Write correct, typed, production-ready code.")
fence = {"luau": "lua", "csharp": "csharp"}


def lines(p):
    return [json.loads(l) for l in filter(str.strip, p.read_text().split("\n"))] if p.exists() else []


LUAU_CAP = 2000  # keep Luau from drowning out the ~200 C# examples
rows, n_luau = [], 0
for r in lines(ROOT / "data/verified/verified.jsonl"):
    if r["lang"] == "luau":
        n_luau += 1
        if n_luau > LUAU_CAP:
            continue
    ans = f"```{fence[r['lang']]}\n{r['code']}\n```"
    if r.get("explanation"):
        ans += "\n\n" + r["explanation"]
    rows.append({"messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": r["prompt"]},
                              {"role": "assistant", "content": ans}], "lang": r["lang"]})
rows += [{"messages": t["messages"], "lang": "3d"} for t in lines(ROOT / "data/traces_3d.jsonl")]
random.Random(0).shuffle(rows)
cut = max(1, len(rows) // 20)
for name, part in (("eval", rows[:cut]), ("sft", rows[cut:])):
    (ROOT / f"data/{name}.jsonl").write_text("\n".join(json.dumps(r) for r in part) + "\n")
counts = {k: sum(r["lang"] == k for r in rows) for k in ("luau", "csharp", "3d")}
print(f"train={len(rows) - cut} eval={cut} {counts}")
