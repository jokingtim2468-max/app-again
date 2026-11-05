"""Entry point for the packaged engine executable (PyInstaller)."""
import sys

from tickbench.__main__ import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["rpc"]))
