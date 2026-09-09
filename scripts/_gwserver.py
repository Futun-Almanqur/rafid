"""Run the gateway on a real TCP socket inside the current process.

    from scripts._gwserver import serve
    with serve() as base:        # e.g. http://127.0.0.1:51234
        ...

Why this exists: the drills and the adapter tests must go over a real socket —
an in-process ASGI call cannot produce a 429 with a Retry-After header that an
HTTP client parses, and that is precisely what phase 5 has to demonstrate. A
uvicorn server in a daemon thread gives a real port without needing a background
process to survive between shell invocations.

Colab uses `scripts/run_gateway.py` (a subprocess) instead; this is for tests.
"""

from __future__ import annotations

import contextlib
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "gateway"))
sys.path.insert(0, str(ROOT / "src"))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextlib.contextmanager
def serve(port: int | None = None, wait_s: float = 30.0):
    import uvicorn

    from app.main import app

    port = port or free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + wait_s
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"{base}/healthz", timeout=1).read()
            break
        except Exception:
            time.sleep(0.1)
    else:
        raise RuntimeError(f"gateway did not come up on {base}")

    try:
        yield base
    finally:
        server.should_exit = True
        thread.join(timeout=10)
