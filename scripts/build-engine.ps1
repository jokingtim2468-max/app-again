# Builds the Python engine into engine/dist/tickbench-engine (PyInstaller one-folder) on Windows.
# Run from the repository root:  powershell -ExecutionPolicy Bypass -File scripts/build-engine.ps1
$ErrorActionPreference = "Stop"
Push-Location engine
try {
  python -m pip install --upgrade pip
  python -m pip install -r requirements-dev.txt
  python -m pytest -q
  if (-not (Test-Path ..\app\build\icon.ico)) { python ..\app\scripts\make_icon.py }
  python -m PyInstaller --noconfirm --clean tickbench-engine.spec
  # self-test of the frozen binary: must answer ping and run a JavaScript strategy (V8 bundled)
  $req = '{"id":1,"method":"ping"}' + "`n" + '{"id":2,"method":"run","params":{"script":{"path":"examples/strategies/sma_cross.js"},"data":{"source":"csv","path":"examples/data/XAUUSD_GC_daily.csv"},"save":false}}'
  $out = $req | .\dist\tickbench-engine\tickbench-engine.exe rpc
  if (-not ($out -match '"netProfit"')) { Write-Output $out; throw "Frozen engine self-test failed" }
  Write-Output "Engine self-test passed"
} finally {
  Pop-Location
}
