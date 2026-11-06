"""Download permissive sources -> data/raw/*.jsonl ({"id","lang","prompt","code","source"}).

Sources (see dataset/sources.csv):
- TorpedoSoftware/Roblox-Luau-Reasoning-v1.0 (MIT): prompts back-generated from Roblox/luau_corpus code.
- vishnuOI/unity-dev-instructions (CC-BY-4.0): ONLY source == "github" rows (MIT/Apache repos).
  stackoverflow rows (CC-BY-SA) and unity_docs rows (Unity copyright) are excluded.
"""
import io, json, pathlib, re, sys
import pandas as pd, requests

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw"; RAW.mkdir(parents=True, exist_ok=True)
HF = "https://huggingface.co/datasets/{}/resolve/main/{}"
LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else 4000


def get(repo, path):
    r = requests.get(HF.format(repo, path), timeout=600); r.raise_for_status(); return r.content


def luau():
    df = pd.read_parquet(io.BytesIO(get("TorpedoSoftware/Roblox-Luau-Reasoning-v1.0", "train.parquet")))
    df = df[df.code.str.len().between(150, 6000)].drop_duplicates("code").head(LIMIT)
    with open(RAW / "luau.jsonl", "w") as f:
        for i, r in df.iterrows():
            f.write(json.dumps({"id": f"luau_{i}", "lang": "luau", "prompt": r.prompt, "code": r.code,
                                "explanation": r.explanation, "source": "Roblox-Luau-Reasoning-v1.0"}) + "\n")
    return len(df)


CODE = re.compile(r"```(?:csharp|cs|c#)?\s*\n(.*?)```", re.S | re.I)


def unity():
    n = 0
    with open(RAW / "csharp.jsonl", "w") as f:
        for line in get("vishnuOI/unity-dev-instructions", "data/train.jsonl").decode().split("\n"):
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("source") != "github":
                continue
            m = CODE.search(r["response"])
            code = (m.group(1) if m else r["response"]).strip()
            if "class " not in code or len(code) > 8000:
                continue
            f.write(json.dumps({"id": r["id"], "lang": "csharp", "prompt": r["instruction"],
                                "code": code, "source": "unity-dev-instructions-github"}) + "\n")
            n += 1
    return n


print("luau", luau()); print("csharp", unity())
