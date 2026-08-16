"""Permite 'python -m src.cli' (seccion 19.3 del plan)."""

from __future__ import annotations

import sys

from src.cli.cli import main

if __name__ == "__main__":
    sys.exit(main())
