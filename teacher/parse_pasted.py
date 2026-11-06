"""Turn pasted chat answers (headers like `p005`: Title) into teacher/answers.jsonl, merged by id.
Usage: python teacher/parse_pasted.py teacher/pasted/*.md && python teacher/ingest.py teacher/answers.jsonl
"""
import json, pathlib, re, sys

HERE = pathlib.Path(__file__).parent
HEAD = re.compile(r"^\W*(p\d{3})\W*:?\s*(.*)$", re.M)
answers = {}
ans_file = HERE / "answers.jsonl"
if ans_file.exists():
    for l in filter(str.strip, ans_file.read_text().split("\n")):
        r = json.loads(l); answers[r["id"]] = r["answer"]
for path in sys.argv[1:]:
    text = pathlib.Path(path).read_text()
    heads = list(HEAD.finditer(text))
    for h, nxt in zip(heads, heads[1:] + [None]):
        body = text[h.end(): nxt.start() if nxt else len(text)]
        body = re.sub(r"^(Lua|Luau|C#|csharp)\s*\n(?=\s*```)", "", body, flags=re.M | re.I)  # drop chat-UI language labels
        answers[h.group(1)] = body.strip()
ans_file.write_text("\n".join(json.dumps({"id": k, "answer": v}) for k, v in sorted(answers.items())) + "\n")
print(f"{len(answers)} answers in {ans_file.name}")
