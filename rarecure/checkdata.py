"""Backward-compatible entry point for data/API checks.

Prefer: python scripts/diagnostic.py  or  python -m rarecure.diagnostic
"""
import sys
from pathlib import Path

if __name__ == "__main__":
    _root = Path(__file__).resolve().parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))
    from rarecure.diagnostic import main
    raise SystemExit(main())
