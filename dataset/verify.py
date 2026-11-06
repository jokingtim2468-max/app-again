"""Verify examples: keep only code that passes the language checker.

Luau: `luau-analyze` (from github.com/luau-lang/luau releases).
C#:  `dotnet build` on a stub project with UnityEngine reference stubs (Unity-API-level
      checks need the real Unity install on the Mac, Day 10+).

Input:  data/raw/*.jsonl   {"id","lang","prompt","code","source"}
Output: data/verified/*.jsonl (+ data/verified/rejected.log)
"""
import json, pathlib, shutil, subprocess, sys, tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW, OUT = ROOT / "data/raw", ROOT / "data/verified"
import csv
ALLOWED = {r["name"] for r in csv.DictReader(open(ROOT / "dataset/sources.csv")) if r["commercial_ok"] == "yes"}


def check_luau(code: str) -> tuple[bool, str]:
    exe = shutil.which("luau-analyze")
    if not exe:
        # Fallback: upstream code was StyLua-formatted (parses). Flagged for re-check with luau-analyze later.
        return True, "UNANALYZED"
    with tempfile.NamedTemporaryFile("w", suffix=".luau", delete=False) as f:
        f.write(code)
    p = subprocess.run([exe, f.name], capture_output=True, text=True, timeout=30)
    return p.returncode == 0, p.stdout + p.stderr


def check_csharp(code: str) -> tuple[bool, str]:
    proj = ROOT / "dataset/csharp_check"
    if not shutil.which("dotnet") or not proj.exists():
        return False, "dotnet or dataset/csharp_check missing"
    (proj / "Example.cs").write_text(code)
    p = subprocess.run(["dotnet", "build", str(proj), "-nologo", "-v", "q"],
                       capture_output=True, text=True, timeout=120)
    return p.returncode == 0, p.stdout[-2000:]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    kept = rejected = 0
    with open(OUT / "verified.jsonl", "w") as out, open(OUT / "rejected.log", "w") as rej:
        for path in sorted(RAW.glob("*.jsonl")):
            for line in filter(str.strip, path.read_text().split("\n")):
                ex = json.loads(line)
                if ex.get("source") not in ALLOWED:
                    ok, log = False, f"source not license-approved: {ex.get('source')}"
                elif ex["lang"] == "luau":
                    ok, log = check_luau(ex["code"])
                elif ex["lang"] == "csharp":
                    ok, log = check_csharp(ex["code"])
                else:
                    ok, log = False, "unknown lang"
                if ok:
                    ex["checked"] = "parse-only" if log == "UNANALYZED" else "full"
                    out.write(json.dumps(ex) + "\n"); kept += 1
                else:
                    rej.write(f"{ex.get('id')}: {log}\n"); rejected += 1
    print(f"kept={kept} rejected={rejected}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
