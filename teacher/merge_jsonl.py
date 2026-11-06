"""Merge uploaded {"id","answer"} JSONL files into teacher/answers.jsonl (newer replaces older)."""
import json, pathlib, sys
HERE = pathlib.Path(__file__).parent
f = HERE / "answers.jsonl"
ans = {r["id"]: r["answer"] for r in map(json.loads, filter(str.strip, f.read_text().split("\n")))} if f.exists() else {}
for path in sys.argv[1:]:
    for l in filter(str.strip, open(path).read().split("\n")):
        r = json.loads(l); ans[r["id"]] = r["answer"]
f.write_text("\n".join(json.dumps({"id": k, "answer": v}) for k, v in sorted(ans.items())) + "\n")
print(len(ans), "answers total")
