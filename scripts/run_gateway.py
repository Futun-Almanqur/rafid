"""Start the local gateway.

    python scripts/run_gateway.py            # port 8080
    PORT=8123 python scripts/run_gateway.py  # anywhere else

The vendored gateway imports its own modules as ``app.*`` — the layout it had in
the course repository, kept unchanged so the vendored files stay diffable against
their source. This launcher puts ``gateway/`` on ``sys.path`` so that import
resolves from any working directory, which is what the Colab setup cell will need
in phase 2.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

GATEWAY = Path(__file__).resolve().parent.parent / "gateway"
sys.path.insert(0, str(GATEWAY))

if __name__ == "__main__":
    import uvicorn

    from app.main import app  # noqa: E402  (sys.path is set above)

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=int(os.environ.get("PORT", "8080")),
        log_level=os.environ.get("LOG_LEVEL", "warning"),
    )
