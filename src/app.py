"""Interfaz grafica: System tray + ventana (seccion 7 del plan, P0-P1).

Las dependencias (pystray, ttkbootstrap, Pillow) son OPCIONALES: si no estan
instaladas, la app informa como instalar la GUI y sugiere el CLI, que tiene
la misma capacidad (paridad garantizada).
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="port-forwarder-gui")
    parser.add_argument("--minimized", action="store_true",
                        help="arranca directo a tray")
    parser.add_argument("--tray-only", action="store_true")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    from src.core.logger import setup_logging

    setup_logging(level=args.log_level, console=False)

    try:
        import pystray  # noqa: F401
        import ttkbootstrap  # noqa: F401
    except ImportError:
        print(
            "GUI no disponible: faltan dependencias opcionales.\n"
            "  pip install pystray ttkbootstrap Pillow winotify\n"
            "Mientras tanto usa el CLI (paridad completa):\n"
            "  python -m src.cli --help",
            file=sys.stderr,
        )
        return 1

    from src.gui.window import run_app

    run_app(minimized=args.minimized, tray_only=args.tray_only)
    return 0


if __name__ == "__main__":
    sys.exit(main())
