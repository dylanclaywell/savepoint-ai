"""PyInstaller entry point — runs the sidecar CLI (see app/main.py:main).

A windowed (console=False) PyInstaller build has no console, so sys.stdout /
sys.stderr are None — and uvicorn's logging crashes writing to them. Point them
at the null device before anything logs.
"""

import os
import sys

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

from app.main import main  # noqa: E402

if __name__ == "__main__":
    main()
