"""Entry point para PyInstaller: 'port-forwarder' (GUI/CLI/API/MCP/web)."""

from __future__ import annotations

import sys

from src.cli.cli import main

if __name__ == "__main__":
    sys.exit(main())
