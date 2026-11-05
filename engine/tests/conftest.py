import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ.setdefault("TICKBENCH_DATA", os.path.join(HERE, ".tbdata"))

EX = os.path.join(ROOT, "examples")
GOLD = os.path.join(EX, "data", "XAUUSD_GC_daily.csv")
