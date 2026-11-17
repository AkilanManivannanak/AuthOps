"""Run the mock portals in a background thread (for scripts and tests)."""
from __future__ import annotations

import socket
import threading
import time

import uvicorn

from authops.portals.app import Chaos, create_app


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class PortalServer:
    def __init__(self, cases_path, chaos: Chaos | None = None, port: int | None = None):
        self.app = create_app(cases_path, chaos)
        self.port = port or free_port()
        self.server = uvicorn.Server(uvicorn.Config(self.app, host="127.0.0.1", port=self.port,
                                                    log_level="warning"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def state(self):
        return self.app.state.portal

    def __enter__(self):
        self.thread.start()
        for _ in range(100):
            if self.server.started:
                return self
            time.sleep(0.05)
        raise RuntimeError("portal server did not start")

    def __exit__(self, *exc):
        self.server.should_exit = True
        self.thread.join(timeout=5)
