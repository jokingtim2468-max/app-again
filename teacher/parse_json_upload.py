"""Parse the uploaded JSON-ish dataset (some entries have unescaped quotes, so regex not json.loads).
Merges into teacher/answers.jsonl as {"id","answer"} with the code in one fenced block."""
import json, pathlib, re, sys

HERE = pathlib.Path(__file__).parent
ENTRY = re.compile(r'"id":\s*"(p\d{3})".*?"engine":\s*"(\w+)".*?"code":\s*"(.*?)",\s*\n\s*"explanation":\s*"(.*?)"\s*\n', re.S)
unesc = lambda s: s.replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"').replace("\\\\", "\\")
ans_file = HERE / "answers.jsonl"
answers = {}
if ans_file.exists():
    for l in filter(str.strip, ans_file.read_text().split("\n")):
        r = json.loads(l); answers[r["id"]] = r["answer"]
found = ENTRY.findall(pathlib.Path(sys.argv[1]).read_text())
for pid, eng, code, expl in found:
    lang = "lua" if eng == "roblox" else "csharp"
    answers[pid] = f"```{lang}\n{unesc(code)}\n```\n\n{unesc(expl)}"
ans_file.write_text("\n".join(json.dumps({"id": k, "answer": v}) for k, v in sorted(answers.items())) + "\n")
print(f"parsed {len(found)} entries: {[f[0] for f in found]}")
