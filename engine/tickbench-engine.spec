# PyInstaller spec for the Tickbench engine (one-folder build). Works on Windows and Linux:
#   python -m PyInstaller --noconfirm --clean tickbench-engine.spec
import glob
import os

import py_mini_racer
from PyInstaller.utils.hooks import collect_all, collect_submodules

HERE = os.path.abspath(SPECPATH)  # noqa: F821 (provided by PyInstaller)

datas = [
    (os.path.join(HERE, "tickbench", "adapters", "jsrt"), os.path.join("tickbench", "adapters", "jsrt")),
    (os.path.join(HERE, "examples"), "examples"),
]
binaries = []
hidden = collect_submodules("tickbench")

for pkg in ("yfinance", "curl_cffi"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hidden += h
    except Exception:
        pass

# py-mini-racer looks for its V8 library next to sys._MEIPASS, so put it at the bundle root.
mr = os.path.dirname(py_mini_racer.__file__)
for f in glob.glob(os.path.join(mr, "*mini_racer*")) + glob.glob(os.path.join(mr, "*.dat")) + glob.glob(os.path.join(mr, "*.bin")):
    if not f.endswith(".py"):
        binaries.append((f, "."))
hidden.append("py_mini_racer.py_mini_racer")

a = Analysis(  # noqa: F821
    [os.path.join(HERE, "engine_main.py")],
    pathex=[HERE],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    excludes=["tkinter", "matplotlib", "IPython", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz, a.scripts, [], exclude_binaries=True, name="tickbench-engine", console=True,
    icon=os.path.join(HERE, "..", "app", "build", "icon.ico") if os.name == "nt" else None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="tickbench-engine")  # noqa: F821
