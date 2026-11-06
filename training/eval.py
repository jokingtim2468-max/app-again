"""Compare base vs adapter on data/eval.jsonl: % of generated code that passes the verifiers.
Run on the GPU pod:  python training/eval.py --adapter out/adapter --n 100
"""
import argparse, json, re, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "dataset"))
from verify import check_luau, check_csharp

p = argparse.ArgumentParser()
p.add_argument("--model", default="Qwen/Qwen3.6-27B")
p.add_argument("--adapter", default=None)
p.add_argument("--n", type=int, default=100)
a = p.parse_args()

from unsloth import FastModel
model, tok = FastModel.from_pretrained(a.adapter or a.model, max_seq_length=4096, load_in_4bit=True)
FastModel.for_inference(model)
tk = getattr(tok, "tokenizer", tok)
rows = [json.loads(l) for l in open("data/eval.jsonl") if l.strip()]
rows = [r for r in rows if r["lang"] in ("luau", "csharp")][: a.n]
ok = {"luau": [0, 0], "csharp": [0, 0]}
for r in rows:
    prompt = tk.apply_chat_template(r["messages"][:2], tokenize=False, add_generation_prompt=True)
    ids = tk(prompt, return_tensors="pt").to(model.device)
    out = tk.decode(model.generate(**ids, max_new_tokens=1024, do_sample=False)[0][ids["input_ids"].shape[1]:], skip_special_tokens=True)
    m = re.search(r"```\w*\n(.*?)```", out, re.S)
    code = m.group(1) if m else out
    passed, _ = (check_luau if r["lang"] == "luau" else check_csharp)(code)
    ok[r["lang"]][0] += passed; ok[r["lang"]][1] += 1
res = {k: f"{v[0]}/{v[1]}" for k, v in ok.items()}
print(json.dumps({"model": a.adapter or a.model, **res}))
