"""Abre la ventana de Port Forwarding Manager (ventana independiente).

Para el acceso directo del Escritorio: la ventana se cierra de verdad al
cerrarla (no queda oculta en bandeja); el proceso en segundo plano (tray)
sigue corriendo y mantiene los tuneles.
"""
from src.core.config import ConfigStore
from src.core.supervisor import Supervisor
from src.gui.window import _open_window

if __name__ == "__main__":
    _open_window(Supervisor(ConfigStore()), close_to_tray=False)
