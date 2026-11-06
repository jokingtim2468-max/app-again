"""Filter teacher output: keep, per prompt, the first answer whose code passes the checks.
Usage: python teacher/ingest.py teacher_raw.jsonl
Writes data/verified/teacher.jsonl (picked up by dataset/build_sft.py) + a pass-rate summary.
"""
import json, pathlib, re, sys
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "dataset"))
from verify import check_csharp, check_luau

STUB = re.compile(r"simulated|placeholder|todo|client script handles|your (own )?logic here|implement (this|here)", re.I)


def quality_problem(code: str, lang: str):
    """Reject answers that compile but would teach bad habits (stubs, missing UI, too short)."""
    lines = [l for l in code.splitlines() if l.strip() and not l.strip().startswith(("--", "//"))]
    if len(lines) < 18:
        return "too_short"
    if STUB.search(code):
        return "stub"
    if lang == "csharp" and re.search(r"\.Q<\w+>\(\s*\"", code):
        return "needs_missing_uxml"  # rules say build UI in code
    return None


FENCE = re.compile(r"```[\w#+-]*\n(.*?)```", re.S)
stats = Counter()
out = open(ROOT / "data/verified/teacher.jsonl", "w")
PROMPTS = {r["id"]: r for r in map(json.loads, filter(str.strip, open(ROOT / "teacher/prompts.jsonl").read().split("\n")))}
for line in filter(str.strip, open(sys.argv[1]).read().split("\n")):
    t = json.loads(line)
    if "candidates" not in t:  # answers from another model: {"id": "p000", "answer": "..."}
        t = {**PROMPTS[t["id"]], "candidates": [t["answer"]]}
    lang = "luau" if t["engine"] == "roblox" else "csharp"
    stats[f"{lang}_prompts"] += 1
    for ans in t["candidates"]:
        blocks = FENCE.findall(ans)
        if len(blocks) != 1 or len(blocks[0]) < 150:
            continue  # want exactly one complete code block
        code = blocks[0]
        reason = quality_problem(code, lang)
        if reason:
            stats[f"reject_{reason}"] += 1
            continue
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
print({k: v for k, v in stats.items() if k.startswith("reject_")})
for lang in ("luau", "csharp"):
    n, k = stats[f"{lang}_prompts"], stats[f"{lang}_kept"]
    print(f"{lang}: kept {k}/{n} ({k / max(n, 1):.0%})")
