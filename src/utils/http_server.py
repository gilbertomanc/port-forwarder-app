"""BoundedThreadingHTTPServer: servidor con limite de conexiones concurrentes.

ThreadingHTTPServer crea un hilo por conexion SIN limite -> un cliente puede
agotar hilos/handles del proceso (CWE-400). Esta variante rechaza conexiones
cuando se supera max_connections y libera el semaforo al terminar el handler.
"""

from __future__ import annotations

import threading
from http.server import ThreadingHTTPServer


class BoundedThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        server_address,
        handler,
        max_connections: int = 50,
        request_queue_size: int = 64,
    ) -> None:
        self._sem = threading.BoundedSemaphore(max_connections)
        self.request_queue_size = request_queue_size
        super().__init__(server_address, handler, bind_and_activate=False)
        self.server_bind()
        self.server_activate()

    def process_request(self, request, client_address) -> None:
        if not self._sem.acquire(blocking=False):
            # Saturado: cerrar la conexion de inmediato (sin hilo nuevo).
            try:
                self.shutdown_request(request)
            except OSError:
                pass
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self._sem.release()
            raise

    def process_request_thread(self, request, client_address) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._sem.release()
