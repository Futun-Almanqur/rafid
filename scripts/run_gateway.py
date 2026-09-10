"""Start the local gateway. One process, in the foreground, nothing forked.

    python scripts/run_gateway.py            # port 8080
    PORT=8123 python scripts/run_gateway.py  # anywhere else

Two properties this file has to keep, because the notebook's restart proof
depends on them (see scripts/gateway_process.py for the bug they fix):

1. **It serves in THIS process.** ``uvicorn.run`` is handed the app object, and
   workers/reload are left off, so uvicorn runs the server inline rather than
   supervising children. The pid the caller holds is the pid bound to the port.
2. **Shutdown is bounded.** ``timeout_graceful_shutdown`` stops uvicorn waiting
   forever for keep-alive connections to drain. An HTTP client with a pooled
   connection open — the SDK adapter has one — can otherwise hold a graceful
   shutdown open indefinitely, and the port keeps answering long after SIGTERM.

The vendored gateway imports its own modules as ``app.*``, the layout it had in
the course repository, kept unchanged so the vendored files stay diffable against
their source. This launcher puts ``gateway/`` on ``sys.path`` instead of editing
them.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

GATEWAY = Path(__file__).resolve().parent.parent / "gateway"
sys.path.insert(0, str(GATEWAY))

#: Seconds uvicorn may spend draining open connections after SIGTERM.
GRACEFUL_SHUTDOWN_SECONDS = 3

if __name__ == "__main__":
    import uvicorn

    from app.main import app  # noqa: E402  (sys.path is set above)

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=int(os.environ.get("PORT", "8080")),
        log_level=os.environ.get("LOG_LEVEL", "warning"),
        # in-process: no supervisor, no reloader, no children
        workers=None,
        reload=False,
        timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_SECONDS,
    )
