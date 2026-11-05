import json
import os
import subprocess
import sys

from conftest import EX, GOLD, ROOT


def test_rpc_roundtrip(tmp_path):
    env = dict(os.environ, TICKBENCH_DATA=str(tmp_path))
    p = subprocess.Popen([sys.executable, "-m", "tickbench", "rpc"], cwd=ROOT, stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, text=True, env=env)
    reqs = [
        {"id": 1, "method": "ping"},
        {"id": 2, "method": "detect", "params": {"path": os.path.join(EX, "strategies", "sma_cross.pine")}},
        {"id": 3, "method": "run", "params": {"script": {"path": os.path.join(EX, "strategies", "sma_cross.pine")},
                                               "data": {"source": "csv", "path": GOLD}}},
        {"id": 4, "method": "runs.list"},
    ]
    out, _ = p.communicate("\n".join(json.dumps(r) for r in reqs) + "\n", timeout=120)
    msgs = [json.loads(l) for l in out.splitlines() if l.strip()]
    by_id = {m["id"]: m for m in msgs if "id" in m and ("result" in m or "error" in m)}
    assert by_id[1]["result"]["version"]
    assert by_id[2]["result"]["type"] == "pine"
    assert by_id[2]["result"]["describe"]["params"][0]["name"] == "fastLen"
    assert by_id[3]["result"]["stats"]["trades"] == 38
    assert any(m.get("event") == "progress" for m in msgs)
    assert by_id[4]["result"][0]["trades"] == 38


def test_script_error_points_at_line():
    from tickbench.errors import ScriptError
    from tickbench.runner import run
    import pytest
    with pytest.raises(ScriptError) as e:
        run({"source": '//@version=5\nstrategy("x")\nx = ta.sma(close, 10)\ny = request.security("AAPL", "D", close)\n',
             "filename": "bad.pine"}, {"source": "csv", "path": GOLD})
    assert e.value.line == 4 and "request.security" in e.value.message
