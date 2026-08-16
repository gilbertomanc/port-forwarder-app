"""Perfiles de exposicion (A2, seccion 11.2): captura y aplicacion.

Aplicar un perfil = transicion: abre lo que falta, cierra lo que sobra
(forwards y tunnels declarados en el perfil).
"""

from __future__ import annotations

from src.core.config import ConfigStore, Profile
from src.core.event_bus import bus
from src.core.supervisor import Supervisor


class Profiles:
    def __init__(self, store: ConfigStore, supervisor: Supervisor) -> None:
        self.store = store
        self.supervisor = supervisor

    def list(self) -> list[Profile]:
        return list(self.store.cfg.profiles)

    def get(self, name: str) -> Profile | None:
        return next((p for p in self.store.cfg.profiles if p.name == name), None)

    def capture(self, name: str, description: str = "") -> Profile:
        """Captura el estado actual (forwards/tunnels con auto) como perfil."""
        profile = Profile(
            name=name,
            description=description,
            forwards=[f.id for f in self.store.cfg.forwards if f.auto_apply],
            tunnels=[t.id for t in self.store.cfg.tunnels if t.auto_start],
        )
        existing = self.get(name)
        if existing:
            self.store.cfg.profiles.remove(existing)
        self.store.cfg.profiles.append(profile)
        self.store.save()
        self.supervisor.metrics.record_event(
            "profile_captured", name=name, forwards=profile.forwards,
            tunnels=profile.tunnels,
        )
        return profile

    def apply(self, name: str) -> Profile:
        profile = self.get(name)
        if profile is None:
            raise ValueError(f"perfil '{name}' no existe")
        cfg = self.store.cfg
        wanted_f = set(profile.forwards)
        wanted_t = set(profile.tunnels)

        # Cierra lo que sobra.
        for f in cfg.forwards:
            if f.auto_apply and f.id not in wanted_f:
                self.supervisor.netsh.remove_forward(f)
                self.supervisor.forward_state[f.id] = "stopped"
        for t in cfg.tunnels:
            if t.auto_start and t.id not in wanted_t and \
                    self.supervisor.ssh.is_alive(t):
                self.supervisor.ssh.stop(t)
                self.supervisor.tunnel_state[t.id] = "stopped"

        # Abre lo que falta.
        for f in cfg.forwards:
            if f.id in wanted_f and not f.auto_apply:
                f.auto_apply = True
        for t in cfg.tunnels:
            if t.id in wanted_t and not t.auto_start:
                t.auto_start = True
        self.store.save()

        self.supervisor.run_once()
        self.supervisor.metrics.record_event(
            "profile_applied", name=name, forwards=sorted(wanted_f),
            tunnels=sorted(wanted_t),
        )
        bus.emit("profile-applied", name=name)
        return profile
