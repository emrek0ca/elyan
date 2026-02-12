#!/usr/bin/env python3
"""Single-file launcher for Wiqo.

Usage:
    python wiqo.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent
    os.chdir(root)
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    from main import main as app_main
    return int(app_main())


if __name__ == "__main__":
    raise SystemExit(main())

