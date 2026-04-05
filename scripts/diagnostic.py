#!/usr/bin/env python3
"""
RareCure diagnostic (CLI wrapper).

    python scripts/diagnostic.py
    python scripts/diagnostic.py --data-only
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rarecure.diagnostic import main

if __name__ == "__main__":
    raise SystemExit(main())
