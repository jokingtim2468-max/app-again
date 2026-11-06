"""Filter teacher output: keep, per prompt, the first answer whose code passes the checks.
Usage: python teacher/ingest.py teacher_raw.jsonl
Writes data/verified/teacher.jsonl (picked up by dataset/build_sft.py) + a pass-rate summary.
"""
import json, pathlib, re, sys
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "dataset"))
from verify import check_csharp, check_luau

FENCE = re.compile(r"```[\w#+-]*\n(.*?)```", re.S)
stats = Counter()
out = open(ROOT / "data/verified/teacher.jsonl", "w")
for line in filter(str.strip, open(sys.argv[1]).read().split("\n")):
    t = json.loads(line)
    lang = "luau" if t["engine"] == "roblox" else "csharp"
    stats[f"{lang}_prompts"] += 1
    for ans in t["candidates"]:
        blocks = FENCE.findall(ans)
        if len(blocks) != 1 or len(blocks[0]) < 150:
            continue  # want exactly one complete code block
        code = blocks[0]
        if lang == "luau":
            ok, log = check_luau(code)
            ok = ok and "--!strict" in code  # extra sanity while luau-analyze is unavailable
        else:
            ok, log = check_csharp(code)
        if ok:
            out.write(json.dumps({"id": t["id"], "lang": lang, "prompt": t["prompt"], "code": code, "response": ans.strip(),
                                  "topic": t["topic"], "source": "teacher-qwen3.5-122b",
                                  "checked": "parse-only" if log == "UNANALYZED" else "full"}) + "\n")
            stats[f"{lang}_kept"] += 1
            break
out.close()
for lang in ("luau", "csharp"):
    n, k = stats[f"{lang}_prompts"], stats[f"{lang}_kept"]
    print(f"{lang}: kept {k}/{n} ({k / max(n, 1):.0%})")
