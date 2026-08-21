"""Ventana principal + tray (seccion 7 del plan).

Ventana con ttkbootstrap: cabecera con estado, Tableview con ordenado por
columnas, filas coloreadas por estado y barra de estado inferior. El
refresco corre en un hilo de fondo: la UI nunca se congela.
"""

from __future__ import annotations

import datetime
import logging
import queue
import threading
import time
import tkinter as tk
from typing import Any

import ttkbootstrap as ttk
from ttkbootstrap.widgets import Tableview

from src.core.config import Bind, ConfigStore, Tunnel, TunnelHealthGate, Vps
from src.core.logger import get_logger
from src.core.supervisor import Supervisor

log = get_logger("port-forwarder.gui")

_FONT = "Segoe UI"
_REFRESH_MS = 5_000

_STATE_COLORS = {
    "ok": "#28a745",
    "running": "#28a745",
    "up": "#28a745",
    "down": "#dc3545",
    "paused": "#ffc107",
    "stopped": "#8f9aa8",
    "missing": "#ffc107",
    "unknown": "#8f9aa8",
}

_FWD_COLUMNS = [
    {"text": "ID", "width": 140},
    {"text": "Listen", "width": 100},
    {"text": "Distro", "width": 150},
    {"text": "WSL Port", "width": 100},
    {"text": "IP", "width": 140},
    {"text": "Estado", "width": 110},
]

_TUN_COLUMNS = [
    {"text": "ID", "width": 130},
    {"text": "Tipo", "width": 80},
    {"text": "VPS", "width": 110},
    {"text": "Local", "width": 140},
    {"text": "Remoto", "width": 180},
    {"text": "Estado", "width": 100},
    {"text": "Tráfico", "width": 170},
]

_VPS_COLUMNS = [
    {"text": "ID", "width": 140},
    {"text": "Host", "width": 220},
    {"text": "Usuario", "width": 140},
    {"text": "Puerto", "width": 90},
]


def _theme_for(cfg_theme: str) -> str:
    return {"dark": "darkly", "light": "flatly"}.get(cfg_theme or "", cfg_theme or "darkly")


def _state_color(state: str) -> str:
    return _STATE_COLORS.get(state, "#8f9aa8")


class BackgroundRefresher:
    """Trabajo pesado en un hilo de fondo; resultado en el hilo principal
    de tkinter via cola + after(). Si ya hay un trabajo en curso se omite."""

    def __init__(self, root: tk.Misc, poll_ms: int = 80) -> None:
        self._root = root
        self._q: queue.Queue = queue.Queue()
        self._busy = False
        root.after(poll_ms, self._poll)

    def submit(self, work, on_done) -> bool:
        if self._busy:
            return False
        self._busy = True
        threading.Thread(target=self._worker, args=(work, on_done), daemon=True).start()
        return True

    def _worker(self, work, on_done) -> None:
        try:
            result = work()
            self._q.put((on_done, result, None))
        except Exception as e:  # noqa: BLE001
            self._q.put((on_done, None, e))
        finally:
            self._q.put((None, None, None))

    def _poll(self) -> None:
        try:
            while True:
                on_done, result, err = self._q.get_nowait()
                if on_done is None:
                    self._busy = False
                else:
                    try:
                        on_done(result, err)
                    except Exception:  # noqa: BLE001
                        logging.getLogger("port-forwarder.gui").exception("on_done fallo")
        except queue.Empty:
            pass
        try:
            self._root.after(80, self._poll)
        except Exception:  # noqa: BLE001 - ventana cerrada
            pass


def _make_table(master, columns: list[dict], iid_field=0) -> Tableview:
    table = Tableview(
        master,
        coldata=columns,
        rowdata=[],
        bootstyle="info",
        stripecolor=("#2a2f37", None),
        searchable=True,
        iid_field=iid_field,
        height=12,
    )
    table.pack(fill="both", expand=True, padx=8, pady=4)
    return table


def _recolor(table: Tableview, color_index: int) -> None:
    """Colorea cada fila segun el estado (ultima columna) usando tags."""
    for state, color in _STATE_COLORS.items():
        table.view.tag_configure(state, foreground=color)
    for row in table.get_rows():
        state = str(row.values[color_index])
        table.view.item(row.iid, tags=[state])


# --- dialogo de formulario generico -----------------------------------------

class _FormDialog(ttk.Toplevel):
    """Dialogo modal generico. rows = [(key, etiqueta, tipo, var, opciones)].

    tipo: "entry" | "combo" | "check". validate(vars) puede lanzar ValueError.
    Al aceptar se llena .result con {key: valor}.
    """

    def __init__(self, parent, title, rows, validate=None) -> None:
        super().__init__(parent)
        self.title(title)
        self.transient(parent)
        self.resizable(False, False)
        self.result = None
        self._validate = validate
        self.vars: dict[str, Any] = {}

        frm = ttk.Frame(self, padding=16)
        frm.pack(fill="both", expand=True)
        for i, (key, label, kind, var, opts) in enumerate(rows):
            ttk.Label(frm, text=label).grid(row=i, column=0, sticky="w", pady=4)
            if isinstance(opts, list):  # compat: lista = valores del combobox
                opts = {"values": opts}
            opts = opts or {}
            if kind == "entry":
                w = ttk.Entry(frm, textvariable=var, width=36,
                              show="*" if opts.get("mask") else "")
            elif kind == "combo":
                w = ttk.Combobox(frm, textvariable=var, values=opts.get("values") or [],
                                 state="readonly", width=34)
            else:  # check
                w = ttk.Checkbutton(frm, text="", variable=var)
            w.grid(row=i, column=1, sticky="w", padx=8, pady=4)
            self.vars[key] = var

        btns = ttk.Frame(frm)
        btns.grid(row=len(rows), column=0, columnspan=2, pady=(12, 0))
        ttk.Button(btns, text="Aceptar", bootstyle="success",
                   command=self._ok).pack(side="left", padx=3)
        ttk.Button(btns, text="Cancelar", bootstyle="secondary",
                   command=self.destroy).pack(side="left", padx=3)
        self.bind("<Return>", lambda _e: self._ok())
        self.bind("<Escape>", lambda _e: self.destroy())
        self.grab_set()

    def _ok(self) -> None:
        try:
            if self._validate and not self._validate(self.vars):
                return
        except ValueError as e:
            from tkinter import messagebox

            messagebox.showerror(self.title(), str(e), parent=self)
            return
        self.result = {k: v.get() for k, v in self.vars.items()}
        self.destroy()


def _parse_bind(text: str, what: str) -> Bind:
    text = (text or "").strip()
    if not text:
        raise ValueError(f"{what} requerido (host:puerto)")
    try:
        host, port = text.rsplit(":", 1)
        port = int(port)
    except ValueError:
        raise ValueError(f"{what} debe ser host:puerto (ej. 0.0.0.0:80)")
    if not host:
        raise ValueError(f"{what}: falta el host")
    return Bind(host=host.strip(), port=port)


# --- acciones de tunnels / vps desde la GUI ----------------------------------

def _selected_tunnel_id(table: Tableview) -> str | None:
    rows = table.get_rows(selected=True)
    return str(rows[0].values[0]) if rows else None


def _selected_vps_id(table: Tableview) -> str | None:
    rows = table.get_rows(selected=True)
    return str(rows[0].values[0]) if rows else None


def _edit_vps_gui(root, sup: Supervisor, vps_table: Tableview, refresh) -> None:
    """Edita un VPS: reusa el formulario de alta precargado con los valores."""
    from tkinter import messagebox

    store = sup.store
    vps_id = _selected_vps_id(vps_table)
    if not vps_id:
        messagebox.showinfo("Port Forwarding", "Selecciona un VPS", parent=root)
        return
    vps = store.get_vps(vps_id)
    if vps is None:
        messagebox.showerror("Port Forwarding", f"VPS '{vps_id}' no existe", parent=root)
        return

    def validate(vars):
        if not vars["host"].get().strip():
            raise ValueError("El host es obligatorio")
        if not vars["user"].get().strip():
            raise ValueError("El usuario es obligatorio")
        return True

    dlg = _FormDialog(root, f"Editar VPS '{vps_id}'", [
        ("host", "Host (IP o dominio)", "entry", tk.StringVar(value=vps.host), None),
        ("user", "Usuario SSH", "entry", tk.StringVar(value=vps.user), None),
        ("port", "Puerto SSH", "entry", tk.StringVar(value=str(vps.port or 22)), None),
        ("identity", "Clave privada (.pem/.key)", "entry", tk.StringVar(value=vps.identity_file or ""), None),
        ("password", "Contrasena SSH (alternativa a la clave)", "entry", tk.StringVar(), {"mask": True}),
    ], validate=validate)
    root.wait_window(dlg)
    if not dlg.result:
        return
    r = dlg.result
    try:
        vps.host = r["host"].strip()
        vps.user = r["user"].strip()
        vps.port = int(r["port"] or 22)
        vps.identity_file = r["identity"].strip() or ""
        if r["password"]:
            vps.password = r["password"]
    except ValueError:
        messagebox.showerror("Editar VPS", "Puerto invalido", parent=root)
        return
    try:
        store.save()
    except Exception as e:  # noqa: BLE001
        messagebox.showerror("Editar VPS", str(e), parent=root)
        return
    refresh()
    messagebox.showinfo("Editar VPS", f"VPS '{vps_id}' actualizado.", parent=root)


def _remove_vps_gui(root, sup: Supervisor, vps_table: Tableview, refresh) -> None:
    from tkinter import messagebox

    store = sup.store
    vps_id = _selected_vps_id(vps_table)
    if not vps_id:
        messagebox.showinfo("Port Forwarding", "Selecciona un VPS", parent=root)
        return
    if not messagebox.askyesno("Port Forwarding", f"Eliminar VPS '{vps_id}'?", parent=root):
        return
    try:
        store.remove_vps(vps_id)
    except Exception as e:  # noqa: BLE001
        messagebox.showerror("Eliminar VPS", str(e), parent=root)
        return
    refresh()
    messagebox.showinfo("Eliminar VPS", f"VPS '{vps_id}' eliminado.", parent=root)


def _add_vps_gui(root, sup: Supervisor, refresh) -> None:
    from tkinter import messagebox

    store = sup.store

    def validate(vars):
        if not vars["id"].get().strip():
            raise ValueError("El ID es obligatorio")
        if not vars["host"].get().strip():
            raise ValueError("El host es obligatorio")
        if not vars["user"].get().strip():
            raise ValueError("El usuario es obligatorio")
        if store.get_vps(vars["id"].get().strip()):
            raise ValueError(f"Ya existe un VPS con id '{vars['id'].get().strip()}'")
        return True

    dlg = _FormDialog(root, "Nuevo VPS", [
        ("id", "ID", "entry", tk.StringVar(), None),
        ("host", "Host (IP o dominio)", "entry", tk.StringVar(), None),
        ("user", "Usuario SSH", "entry", tk.StringVar(), None),
        ("port", "Puerto SSH", "entry", tk.StringVar(value="22"), None),
        ("identity", "Clave privada (.pem/.key)", "entry", tk.StringVar(), None),
        ("password", "Contrasena SSH (alternativa a la clave)", "entry", tk.StringVar(), {"mask": True}),
    ], validate=validate)
    root.wait_window(dlg)
    if not dlg.result:
        return
    r = dlg.result
    try:
        store.add_vps(Vps(
            id=r["id"].strip(),
            host=r["host"].strip(),
            user=r["user"].strip(),
            port=int(r["port"] or 22),
            identity_file=r["identity"].strip() or "",
            password=r["password"] or "",
        ))
    except ValueError:
        messagebox.showerror("Nuevo VPS", "Puerto invalido", parent=root)
        return
    refresh()
    messagebox.showinfo("Nuevo VPS",
                        f"VPS '{r['id'].strip()}' agregado.", parent=root)


def _add_tunnel_gui(root, sup: Supervisor, refresh) -> None:
    from tkinter import messagebox

    store = sup.store
    vps_ids = [v.id for v in store.cfg.vps_list]
    if not vps_ids:
        messagebox.showwarning(
            "Nuevo tunnel",
            "Primero registra un VPS (boton 'Nuevo VPS...'):\n"
            "el tunnel ssh reenvia el servicio local a traves de el.",
            parent=root,
        )
        return

    def validate(vars):
        tid = vars["id"].get().strip()
        if not tid:
            raise ValueError("El ID es obligatorio")
        if store.get_tunnel(tid):
            raise ValueError(f"Ya existe un tunnel con id '{tid}'")
        if not vars["vps"].get():
            raise ValueError("Selecciona un VPS")
        _parse_bind(vars["local"].get(), "Local")
        remotes = [s for s in vars["remotes"].get().split(",") if s.strip()]
        if not remotes:
            raise ValueError("Al menos un bind remoto (host:puerto)")
        for s in remotes:
            _parse_bind(s, "Remoto")
        return True

    dlg = _FormDialog(root, "Nuevo tunnel", [
        ("id", "ID", "entry", tk.StringVar(), None),
        ("vps", "VPS", "combo", tk.StringVar(value=vps_ids[0]), vps_ids),
        ("local", "Local (host:puerto)", "entry", tk.StringVar(value="127.0.0.1:3000"), None),
        ("remotes", "Remotos (host:puerto, separados por coma)", "entry", tk.StringVar(value="0.0.0.0:80"), None),
        ("auto_start", "Auto-arranque (supervisor lo mantiene vivo)", "check", tk.BooleanVar(value=True), None),
        ("health_gate", "Health gate (solo abre si el servicio local responde)", "check", tk.BooleanVar(value=True), None),
    ], validate=validate)
    root.wait_window(dlg)
    if not dlg.result:
        return
    r = dlg.result
    try:
        tun = Tunnel(
            id=r["id"].strip(),
            vps_id=r["vps"],
            local_bind=_parse_bind(r["local"], "Local"),
            remote_binds=[_parse_bind(s, "Remoto") for s in r["remotes"].split(",") if s.strip()],
            auto_start=bool(r["auto_start"]),
            health_gate=TunnelHealthGate(enabled=bool(r["health_gate"])),
        )
        store.add_tunnel(tun)
    except Exception as e:  # noqa: BLE001
        messagebox.showerror("Nuevo tunnel", str(e), parent=root)
        return
    if tun.auto_start:
        try:
            sup.ssh.start(tun, store.get_vps(tun.vps_id))
        except Exception as e:  # noqa: BLE001
            messagebox.showwarning(
                "Nuevo tunnel",
                f"Tunnel creado pero no pudo arrancar: {e}\n"
                "El supervisor reintentara automaticamente.",
                parent=root,
            )
    refresh()
    messagebox.showinfo("Nuevo tunnel",
                        f"Tunnel '{tun.id}' creado.", parent=root)


def _tunnel_action(sup: Supervisor, action: str, table: Tableview, refresh) -> None:
    from tkinter import messagebox

    tid = _selected_tunnel_id(table)
    if not tid:
        messagebox.showinfo("Port Forwarding", "Selecciona un tunnel", parent=table.winfo_toplevel())
        return
    store = sup.store
    tun = store.get_tunnel(tid)
    if tun is None:
        messagebox.showerror("Port Forwarding", f"Tunnel '{tid}' no existe", parent=table.winfo_toplevel())
        return
    try:
        if action == "start":
            vps = store.get_vps(tun.vps_id) if tun.type == "ssh" else None
            sup.ssh.start(tun, vps)
        elif action == "stop":
            sup.ssh.stop(tun)
        elif action == "remove":
            if not messagebox.askyesno("Port Forwarding", f"Eliminar tunnel '{tid}'?", parent=table.winfo_toplevel()):
                return
            try:
                sup.ssh.stop(tun)
            except Exception:  # noqa: BLE001
                pass
            store.remove_tunnel(tid)
    except Exception as e:  # noqa: BLE001
        messagebox.showerror("Port Forwarding", str(e), parent=table.winfo_toplevel())
        return
    refresh()


def run_app(minimized: bool = False, tray_only: bool = False) -> None:
    """Entry point de la GUI. Requiere pystray + ttkbootstrap instalados."""
    import pystray
    from PIL import Image, ImageDraw

    store = ConfigStore()
    sup = Supervisor(store)
    sup.start()

    # API REST: arranca en segundo plano si esta habilitada en config (21).
    api_server = None
    if store.cfg.api.enabled:
        try:
            from src.api.auth import AuthService
            from src.api.server import ApiServer
            from src.api.service import AppService

            api_server = ApiServer(AppService(store, sup), AuthService(),
                                   host=store.cfg.api.host,
                                   port=store.cfg.api.port,
                                   allowed_ips=store.cfg.api.allowed_ips)
            api_server.start()
        except Exception as e:
            log.warning("API no arranco: %s", e)
            api_server = None

    def _shutdown() -> None:
        # Ajustes: "Al salir mantener tuneles vivos" (on_close.keep_tunnels_alive).
        if not store.cfg.on_close.keep_tunnels_alive:
            for t in store.cfg.tunnels:
                try:
                    sup.ssh.stop(t)
                except Exception:  # noqa: BLE001
                    pass
        if api_server:
            api_server.stop()
        sup.stop()

    def _make_icon(state: str = "ok"):
        img = Image.new("RGB", (64, 64), (30, 30, 30))
        draw = ImageDraw.Draw(img)
        color = {"ok": (76, 175, 80), "warn": (255, 193, 7),
                 "error": (244, 67, 54)}.get(state, (76, 175, 80))
        draw.ellipse((8, 8, 56, 56), fill=color)
        draw.rectangle((24, 30, 40, 44), fill=(30, 30, 30))
        return img

    def _tooltip() -> str:
        st = sup.status()
        up = sum(1 for f in st["forwards"] if f["state"] == "ok")
        tun_up = sum(1 for t in st["tunnels"] if t["state"] == "running")
        return (f"Port Forwarding Manager\n"
                f"forwards OK: {up}/{len(st['forwards'])}  "
                f"tunnels: {tun_up}/{len(st['tunnels'])}"
                + ("\nMANTENIMIENTO" if st["maintenance"] else ""))

    menu = pystray.Menu(
        pystray.MenuItem(lambda item: _tooltip().splitlines()[0],
                         None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Estado", lambda: None, enabled=False),
        pystray.MenuItem("Mostrar", lambda icon, item: _show(icon, sup),
                         default=True),
        pystray.MenuItem("Reaplicar todo",
                         lambda icon, item: sup.run_once()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Salir", lambda icon, item: _quit(icon, sup)),
    )

    icon = pystray.Icon("port-forwarder", _make_icon(), _tooltip(), menu)
    threading.Thread(
        target=_tray_tooltip_updater, args=(icon, sup), daemon=True
    ).start()

    def _show(icon: pystray.Icon, sup: Supervisor) -> None:
        if tray_only:
            return
        _open_window(sup)

    def _quit(icon: pystray.Icon, sup: Supervisor) -> None:
        _shutdown()
        icon.stop()

    icon.run()


def _tray_tooltip_updater(icon: Any, sup: Supervisor) -> None:
    while True:
        try:
            icon.title = _tooltip(sup)
        except Exception:
            pass
        time.sleep(60)


def _tooltip(sup: Supervisor) -> str:
    st = sup.status()
    up = sum(1 for f in st["forwards"] if f["state"] == "ok")
    tun_up = sum(1 for t in st["tunnels"] if t["state"] == "running")
    return (f"Port Forwarding Manager | fwd {up}/{len(st['forwards'])} "
            f"tun {tun_up}/{len(st['tunnels'])}")


def _build_settings_tab(nb, sup: Supervisor, root) -> None:
    """Pestana Ajustes: tema, segundo plano, autoarranque, panel web
    (clave obligatoria), MCP y API."""
    import webbrowser
    from pathlib import Path
    from tkinter import messagebox
    from winreg import HKEY_CURRENT_USER, CreateKey, DeleteValue, OpenKey, QueryValueEx, SetValueEx

    store = sup.store
    ui = store.cfg.ui
    api = store.cfg.api
    mcp = store.cfg.mcp

    RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
    AUTOSTART_NAME = "PortForwarder"

    def _auto_command() -> str:
        vbs = Path(__file__).resolve().parents[2] / "start_port_forwarder.vbs"
        return f'wscript.exe "{vbs}"'

    def _ensure_auto_vbs() -> None:
        """Crea el lanzador VBS (ventana oculta) si no existe: el autoarranque
        via wscript necesita ese archivo y, sin el, podia abrirse una terminal
        o un error breve al iniciar sesion."""
        vbs = Path(__file__).resolve().parents[2] / "start_port_forwarder.vbs"
        if vbs.exists():
            return
        content = (
            "' Lanzador oculto de Port Forwarding (auto-generado): pythonw, SIN terminal.\n"
            "Set sh = CreateObject(\"WScript.Shell\")\n"
            "Set fso = CreateObject(\"Scripting.FileSystemObject\")\n"
            "dir = fso.GetParentFolderName(WScript.ScriptFullName)\n"
            "sh.Run \"\"\"\" & dir & \"\\.venv\\Scripts\\pythonw.exe\"\""
            " -m src.cli web start\", 0, False\n"
        )
        try:
            vbs.write_text(content, encoding="utf-8")
        except OSError:
            pass

    def _auto_active() -> bool:
        try:
            with OpenKey(HKEY_CURRENT_USER, RUN_KEY) as k:
                return QueryValueEx(k, AUTOSTART_NAME)[0] == _auto_command()
        except OSError:
            return False

    def _set_auto(active: bool) -> None:
        if active:
            _ensure_auto_vbs()
        with CreateKey(HKEY_CURRENT_USER, RUN_KEY) as k:
            if active:
                SetValueEx(k, AUTOSTART_NAME, 0, 1, _auto_command())  # REG_SZ
            else:
                try:
                    DeleteValue(k, AUTOSTART_NAME)
                except OSError:
                    pass

    tab = ttk.Frame(nb)
    nb.add(tab, text="Ajustes")
    form = ttk.Frame(tab)
    form.pack(fill="x", padx=12, pady=10)

    # -- general --------------------------------------------------------------
    ttk.Label(form, text="General", style="Header.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 4))
    theme_var = tk.StringVar(value=ui.theme if ui.theme != "dark" else "darkly")
    ttk.Label(form, text="Tema:").grid(row=1, column=0, sticky="w")
    ttk.Combobox(form, textvariable=theme_var, values=["darkly", "superhero", "cyborg", "cosmo", "flatly", "journal"], state="readonly", width=14).grid(row=1, column=1, sticky="w", padx=6)
    tray_var = tk.BooleanVar(value=ui.close_to_tray)
    ttk.Checkbutton(form, text="Ejecutar en segundo plano: cerrar ventana -> minimizar a bandeja (la app sigue viva)", variable=tray_var).grid(row=2, column=0, columnspan=3, sticky="w", pady=3)
    auto_var = tk.BooleanVar(value=_auto_active())
    ttk.Checkbutton(form, text="Autoarranque: iniciar con Windows en segundo plano (bandeja)", variable=auto_var).grid(row=3, column=0, columnspan=3, sticky="w", pady=3)
    keep_var = tk.BooleanVar(value=store.cfg.on_close.keep_tunnels_alive)
    ttk.Checkbutton(form, text="Al salir de la app: mantener los tuneles vivos (no detenerlos)", variable=keep_var).grid(row=4, column=0, columnspan=3, sticky="w", pady=3)

    ttk.Separator(form).grid(row=5, column=0, columnspan=3, sticky="ew", pady=8)

    # -- panel web ----------------------------------------------------------
    ttk.Label(form, text="Panel web", style="Header.TLabel").grid(row=6, column=0, columnspan=3, sticky="w", pady=(0, 4))
    web_var = tk.BooleanVar(value=ui.web_panel_enabled)
    ttk.Checkbutton(form, text="Panel web habilitado", variable=web_var).grid(row=7, column=0, columnspan=2, sticky="w", pady=3)
    web_port_var = tk.StringVar(value=str(ui.web_panel_port))
    ttk.Label(form, text="Puerto:").grid(row=8, column=0, sticky="w")
    ttk.Entry(form, textvariable=web_port_var, width=8).grid(row=8, column=1, sticky="w", padx=6)
    web_bind_var = tk.StringVar(value=ui.web_panel_bind)
    ttk.Label(form, text="Bind:").grid(row=9, column=0, sticky="w")
    ttk.Entry(form, textvariable=web_bind_var, width=14).grid(row=9, column=1, sticky="w", padx=6)
    web_pw_var = tk.StringVar()
    ttk.Label(form, text="Clave (obligatoria):").grid(row=10, column=0, sticky="w")
    ttk.Entry(form, textvariable=web_pw_var, width=22, show="*").grid(row=10, column=1, sticky="w", padx=6)
    ttk.Label(form, text="Sin clave el panel no arranca. Si la dejas vacia se conserva la actual.", style="Muted.TLabel").grid(row=11, column=0, columnspan=3, sticky="w")

    ttk.Separator(form).grid(row=12, column=0, columnspan=3, sticky="ew", pady=8)

    # -- MCP ----------------------------------------------------------------
    ttk.Label(form, text="Servidor MCP (agentes LLM)", style="Header.TLabel").grid(row=13, column=0, columnspan=3, sticky="w", pady=(0, 4))
    mcp_var = tk.BooleanVar(value=mcp.enabled)
    ttk.Checkbutton(form, text="MCP habilitado", variable=mcp_var).grid(row=14, column=0, columnspan=2, sticky="w", pady=3)
    mcp_transport_var = tk.StringVar(value=mcp.transport)
    ttk.Label(form, text="Transporte:").grid(row=15, column=0, sticky="w")
    ttk.Combobox(form, textvariable=mcp_transport_var, values=["stdio", "http"], state="readonly", width=8).grid(row=15, column=1, sticky="w", padx=6)
    mcp_port_var = tk.StringVar(value=str(mcp.port))
    ttk.Label(form, text="Puerto (http):").grid(row=16, column=0, sticky="w")
    ttk.Entry(form, textvariable=mcp_port_var, width=8).grid(row=16, column=1, sticky="w", padx=6)
    mcp_token_var = tk.BooleanVar(value=mcp.token_required)
    ttk.Checkbutton(form, text="Exigir token", variable=mcp_token_var).grid(row=17, column=0, columnspan=2, sticky="w", pady=3)
    mcp_key_var = tk.StringVar()
    ttk.Label(form, text="Token:").grid(row=18, column=0, sticky="w")
    ttk.Entry(form, textvariable=mcp_key_var, width=22, show="*").grid(row=18, column=1, sticky="w", padx=6)
    ttk.Label(form, text="Si exiges token y lo dejas vacio, se genera uno aleatorio.", style="Muted.TLabel").grid(row=19, column=0, columnspan=3, sticky="w")

    ttk.Separator(form).grid(row=20, column=0, columnspan=3, sticky="ew", pady=8)

    # -- API -----------------------------------------------------------------
    ttk.Label(form, text="API REST", style="Header.TLabel").grid(row=21, column=0, columnspan=3, sticky="w", pady=(0, 4))
    api_var = tk.BooleanVar(value=api.enabled)
    ttk.Checkbutton(form, text="API REST habilitada (loopback)", variable=api_var).grid(row=22, column=0, columnspan=2, sticky="w", pady=3)
    api_port_var = tk.StringVar(value=str(api.port))
    ttk.Label(form, text="Puerto API:").grid(row=23, column=0, sticky="w")
    ttk.Entry(form, textvariable=api_port_var, width=8).grid(row=23, column=1, sticky="w", padx=6)
    api_scope_var = tk.StringVar(value="write")
    ttk.Label(form, text="Scope del token:").grid(row=24, column=0, sticky="w")
    ttk.Combobox(form, textvariable=api_scope_var, values=["read", "write", "admin"], state="readonly", width=8).grid(row=24, column=1, sticky="w", padx=6)

    def _gen_api_token() -> None:
        """Crea un token para la API REST (equivale a 'api tokens create')."""
        from src.api.auth import AuthService

        scope = api_scope_var.get()
        try:
            _tid, token = AuthService().create_token(scope)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Port Forwarding", f"No se pudo generar el token: {e}", parent=root)
            return
        messagebox.showinfo(
            "Port Forwarding",
            "Token API generado (scope %s).\n\n%s\n\nGuardalo: NO se volvera a mostrar.\n"
            "Uso: Authorization: Bearer %s" % (scope, token, token),
            parent=root,
        )

    ttk.Button(form, text="Generar token API", bootstyle="info", command=_gen_api_token).grid(row=25, column=1, sticky="w", padx=6, pady=3)
    ttk.Label(form, text="El token se genera (no se escribe) y se guarda con hash; se muestra UNA sola vez.", style="Muted.TLabel").grid(row=26, column=0, columnspan=3, sticky="w")

    btns = ttk.Frame(form)
    btns.grid(row=27, column=0, columnspan=3, sticky="w", pady=10)
    ttk.Button(btns, text="Guardar ajustes", bootstyle="info", command=lambda: _save()).pack(side="left", padx=2)
    ttk.Button(btns, text="Abrir panel web", bootstyle="success", command=lambda: _open_web()).pack(side="left", padx=2)

    def _save() -> None:
        try:
            web_port = int(web_port_var.get() or 8794)
            api_port = int(api_port_var.get() or 8795)
            mcp_port = int(mcp_port_var.get() or 8796)
        except ValueError:
            messagebox.showerror("Port Forwarding", "Puertos invalidos", parent=root)
            return

        cfg = store.cfg
        web_on = web_var.get()
        web_pw = web_pw_var.get()
        # El token del panel vive en SecretsStore (DPAPI) o en config (legacy).
        from src.utils.secrets import SecretsStore

        _sec = SecretsStore()
        has_token = bool(cfg.ui.web_panel_token) or _sec.check("web_panel_token")
        if web_on and not web_pw and not has_token:
            messagebox.showerror(
                "Port Forwarding",
                "El panel web debe tener una clave (obligatoria).\n"
                "Escribela o desactiva el panel.",
                parent=root,
            )
            return
        cfg.ui.theme = theme_var.get()
        cfg.ui.close_to_tray = tray_var.get()
        cfg.on_close.keep_tunnels_alive = keep_var.get()
        cfg.ui.web_panel_enabled = web_on
        cfg.ui.web_panel_port = web_port
        cfg.ui.web_panel_bind = web_bind_var.get().strip() or "127.0.0.1"
        if web_pw:
            # La clave se guarda SOLO cifrada (DPAPI) en secrets; nunca en claro.
            _sec.set("web_panel_token", web_pw)
            cfg.ui.web_panel_token = ""

        mcp_on = mcp_var.get()
        mcp_token = mcp_key_var.get()
        generated = None
        if mcp_on and mcp_token_var.get() and not mcp_token and not cfg.mcp.token:
            import secrets

            generated = secrets.token_urlsafe(24)
            mcp_token = generated
        cfg.mcp.enabled = mcp_on
        cfg.mcp.transport = mcp_transport_var.get()
        cfg.mcp.port = mcp_port
        cfg.mcp.token_required = mcp_token_var.get()
        if mcp_token:
            cfg.mcp.token = mcp_token

        cfg.api.enabled = api_var.get()
        cfg.api.port = api_port

        # Autoarranque con Windows (HKCU Run): en segundo plano via VBS.
        _set_auto(auto_var.get())

        try:
            store.save()
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Port Forwarding", str(e), parent=root)
            return
        msg = "Ajustes guardados. El panel web arranca/para solo en segundos."
        if generated:
            msg += f"\n\nToken MCP generado: {generated}"
        if auto_var.get():
            msg += "\n\nAutoarranque con Windows: ACTIVADO (inicia en segundo plano)."
        messagebox.showinfo("Port Forwarding", msg, parent=root)

    def _open_web() -> None:
        cfg = store.cfg
        webbrowser.open(f"http://{cfg.ui.web_panel_bind or '127.0.0.1'}:{cfg.ui.web_panel_port}")


def _open_window(sup: Supervisor, close_to_tray: bool | None = None) -> None:
    """Ventana ttkbootstrap con pestanas Forwards/Tunnels/Logs.

    close_to_tray: None = leer config; False = cerrar destruye la ventana
    (para la ventana independiente / acceso directo del Escritorio).
    """
    root = ttk.Window(
        themename=_theme_for(sup.store.cfg.ui.theme),
        title="Port Forwarding Manager",
    )
    root.geometry("1020x640")
    root.minsize(840, 500)

    def _on_close() -> None:
        # Ajustes: "Ejecutar en segundo plano" -> cerrar minimiza a bandeja.
        cfg_close = sup.store.cfg.ui.close_to_tray
        if (close_to_tray is None and cfg_close) or close_to_tray is True:
            root.withdraw()
            return
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", _on_close)

    style = ttk.Style()
    style.configure("Treeview", rowheight=28, font=(_FONT, 10))
    style.configure("Treeview.Heading", font=(_FONT, 10, "bold"))
    style.configure("TNotebook.Tab", font=(_FONT, 10), padding=(16, 7))
    style.configure("Header.TLabel", font=(_FONT, 14, "bold"))
    style.configure("Muted.TLabel", foreground="#8f9aa8")

    bg = BackgroundRefresher(root)

    # cabecera
    header = ttk.Frame(root, padding=(16, 12))
    header.pack(fill="x")
    ttk.Label(header, text="Port Forwarding Manager", style="Header.TLabel").pack(side="left")
    ttk.Label(header, text="forwards Windows->WSL y tuneles hacia VPS", style="Muted.TLabel").pack(side="left", padx=(10, 0))
    header_status = ttk.Label(header, text="", style="Muted.TLabel")
    header_status.pack(side="right")
    ttk.Separator(root).pack(fill="x")

    nb = ttk.Notebook(root, padding=6)
    nb.pack(fill="both", expand=True, padx=8, pady=(4, 0))

    # --- pestana Forwards -----------------------------------------------------
    fwd_tab = ttk.Frame(nb)
    nb.add(fwd_tab, text="Forwards")
    fwd_bar = ttk.Frame(fwd_tab)
    fwd_bar.pack(fill="x", padx=6, pady=6)
    ttk.Button(fwd_bar, text="Refrescar", bootstyle="success",
               command=lambda: _refresh()).pack(side="left", padx=2)
    ttk.Button(fwd_bar, text="Reaplicar todos", bootstyle="info",
               command=lambda: (sup.run_once(), _refresh())).pack(side="left", padx=2)
    fwd_table = _make_table(fwd_tab, _FWD_COLUMNS)

    # --- pestana Tunnels ------------------------------------------------------
    tun_tab = ttk.Frame(nb)
    nb.add(tun_tab, text="Tunnels")
    tun_bar = ttk.Frame(tun_tab)
    tun_bar.pack(fill="x", padx=6, pady=6)
    ttk.Button(tun_bar, text="Nuevo tunnel...", bootstyle="info",
               command=lambda: _add_tunnel_gui(root, sup, _refresh)).pack(side="left", padx=2)
    ttk.Button(tun_bar, text="Iniciar", bootstyle="success",
               command=lambda: _tunnel_action(sup, "start", tun_table, _refresh)).pack(side="left", padx=2)
    ttk.Button(tun_bar, text="Detener", bootstyle="warning",
               command=lambda: _tunnel_action(sup, "stop", tun_table, _refresh)).pack(side="left", padx=2)
    ttk.Button(tun_bar, text="Eliminar", bootstyle="danger",
               command=lambda: _tunnel_action(sup, "remove", tun_table, _refresh)).pack(side="left", padx=2)
    tun_table = _make_table(tun_tab, _TUN_COLUMNS)

    # --- seccion VPS ----------------------------------------------------------
    vps_frame = ttk.Frame(tun_tab)
    vps_frame.pack(fill="both", expand=True, padx=6, pady=(12, 6))
    vps_bar = ttk.Frame(vps_frame)
    vps_bar.pack(fill="x")
    ttk.Label(vps_bar, text="Servidores VPS", style="Header.TLabel").pack(side="left", padx=(0, 10))
    ttk.Button(vps_bar, text="Nuevo VPS...", bootstyle="info",
               command=lambda: _add_vps_gui(root, sup, _refresh)).pack(side="left", padx=2)
    ttk.Button(vps_bar, text="Editar...", bootstyle="secondary",
               command=lambda: _edit_vps_gui(root, sup, vps_table, _refresh)).pack(side="left", padx=2)
    ttk.Button(vps_bar, text="Eliminar", bootstyle="danger",
               command=lambda: _remove_vps_gui(root, sup, vps_table, _refresh)).pack(side="left", padx=2)
    vps_table = _make_table(vps_frame, _VPS_COLUMNS)
    # --- pestana Logs ---------------------------------------------------------
    log_tab = ttk.Frame(nb)
    nb.add(log_tab, text="Logs")
    log_bar = ttk.Frame(log_tab)
    log_bar.pack(fill="x", padx=6, pady=6)
    ttk.Button(log_bar, text="Refrescar", bootstyle="success",
               command=lambda: _refresh_logs()).pack(side="left", padx=2)
    ttk.Label(log_bar, text="  Ultimas lineas de port-forwarder.log", style="Muted.TLabel").pack(side="left")
    log_text = tk.Text(log_tab, wrap="none", font=("Consolas", 9), state="disabled", bg="#17191d", fg="#c9d1d9")
    log_text.pack(fill="both", expand=True, padx=8, pady=(0, 6))

    # --- pestana Ajustes ------------------------------------------------------
    _build_settings_tab(nb, sup, root)

    # --- barra de estado ------------------------------------------------------
    ttk.Separator(root).pack(fill="x")
    bar = ttk.Frame(root, padding=(16, 6))
    bar.pack(fill="x", side="bottom")
    status_var = tk.StringVar(value="cargando...")
    ttk.Label(bar, textvariable=status_var, style="Muted.TLabel").pack(side="left")
    ttk.Label(bar, text="ejecutando en segundo plano (bandeja del sistema)", style="Muted.TLabel").pack(side="right")

    # --- refresco -------------------------------------------------------------
    def _preserve_and_rebuild(table: Tableview, columns: list[dict], rows: list[list]) -> None:
        prev = table.view.selection()
        prev_search = table.searchcriteria
        table.build_table_data(columns, rows)
        if prev_search:
            table.searchcriteria = prev_search
            table.search_table_data(prev_search)
        for iid in prev:
            if table.view.exists(iid):
                table.view.selection_set(iid)
                table.view.focus(iid)
                table.view.see(iid)

    def _refresh() -> None:
        bg.submit(_work, _on_status)

    def _work():
        st = sup.status()
        tr: dict[str, dict] = {}
        for t in sup.store.cfg.tunnels:
            try:
                if sup.ssh.is_alive(t):
                    tf = sup.ssh.traffic(t, sup.store.get_vps(t.vps_id))
                    if tf:
                        tr[t.id] = tf
            except Exception:  # noqa: BLE001
                continue
        return st, tr

    def _fmt_bytes(n: int) -> str:
        n = float(n or 0)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if n < 1024 or unit == "TB":
                return f"{n:.1f} {unit}"
            n /= 1024
        return f"{n:.1f} TB"

    def _fmt_traffic(tf: dict) -> str:
        if not tf:
            return "-"
        return (f"rx {_fmt_bytes(tf['rx_bytes'])} · tx {_fmt_bytes(tf['tx_bytes'])}"
                f"  ↓{_fmt_bytes(tf['rx_rate_bps'])}/s ↑{_fmt_bytes(tf['tx_rate_bps'])}/s")

    def _on_status(result, err) -> None:
        if err is not None or result is None:
            status_var.set(f"error: {err}")
            return
        status, traffic = result
        fwd_rows = [
            [f["id"], str(f["listen_port"]), f["wsl_distro"], str(f["wsl_port"]),
             f.get("ip") or "-", f["state"]]
            for f in status["forwards"]
        ]
        _preserve_and_rebuild(fwd_table, _FWD_COLUMNS, fwd_rows)
        _recolor(fwd_table, 5)

        tun_rows = [
            [t["id"], t["type"], t["vps_id"], t["local"],
             ", ".join(t["remote"]), t["state"], _fmt_traffic(traffic.get(t["id"]))]
            for t in status["tunnels"]
        ]
        _preserve_and_rebuild(tun_table, _TUN_COLUMNS, tun_rows)
        _recolor(tun_table, 5)

        vps_rows = [
            [v.id, v.host, v.user, str(v.port or 22)]
            for v in sup.store.cfg.vps_list
        ]
        _preserve_and_rebuild(vps_table, _VPS_COLUMNS, vps_rows)

        fwd_ok = sum(1 for f in status["forwards"] if f["state"] == "ok")
        tun_ok = sum(1 for t in status["tunnels"] if t["state"] == "running")
        header_status.configure(
            text=f"forwards {fwd_ok}/{len(status['forwards'])}  |  "
                 f"tunnels {tun_ok}/{len(status['tunnels'])}"
                 + ("  |  MANTENIMIENTO" if status["maintenance"] else "")
        )
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        status_var.set(f"actualizado {ts}  |  administrador: "
                       f"{'si' if status.get('admin') else 'no'}"
                       + ("  |  MANTENIMIENTO ACTIVO" if status["maintenance"] else ""))

    def _refresh_logs() -> None:
        bg.submit(_read_logs, _apply_logs)

    def _read_logs() -> str:
        from src.utils import path as paths

        try:
            p = paths.logs_dir() / "port-forwarder.log"
            if not p.exists():
                return "(sin log todavia)"
            return p.read_text(encoding="utf-8", errors="replace")[-4000:]
        except OSError:
            return "(no se pudo leer el log)"

    def _apply_logs(content, err) -> None:
        if err is not None:
            return
        log_text.configure(state="normal")
        log_text.delete("1.0", "end")
        log_text.insert("end", content)
        log_text.configure(state="disabled")

    def _schedule() -> None:
        _refresh()
        _refresh_logs()
        root.after(_REFRESH_MS, _schedule)

    _refresh()
    _schedule()
    root.mainloop()
