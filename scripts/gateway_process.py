"""Owning the gateway process, so that terminating it really terminates it.

THE BUG THIS EXISTS FOR. On a clean Colab runtime, §0.4's restart proof failed:

    terminated : returncode = -15        <- the child really did die
    GET /healthz                          <- ...and the port still answered
    AssertionError: something is still answering on the port

A returncode of -15 with a live port means the handle the notebook held was not
the only thing bound to that socket. `Popen.terminate()` signals **one process**.
Anything that process forked — a supervisor's worker, a reloader child, a
grandchild that inherited the listening file descriptor — keeps the socket open
and keeps answering, and the notebook has no handle on it.

The fix is ownership, in three parts, none of which is a sleep:

1. **`start_new_session=True`** puts the gateway in its own process group and
   session. Everything it forks lands in that group and nothing else does.
2. **Shutdown signals the whole group** (`os.killpg`), SIGTERM first for a clean
   exit, then SIGKILL only for what is still alive after a grace period. Only
   this group is ever signalled — never a pid we did not create.
3. **The port is the authority, not the process.** `wait_until_port_closed()`
   polls with a real TCP connect until the port refuses. A process object saying
   "returncode = -15" is not evidence the socket is gone; a refused connection is.

The notebook and `scripts/verify_lifecycle.py` both use these functions, so the
lifecycle test proves the code path the notebook actually runs.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: How long a well-behaved gateway gets to shut down before SIGKILL.
GRACE_SECONDS = 5.0


def free_port() -> int:
    """Ask the kernel for a port nobody is using, then let it go."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def port_is_open(port: int, host: str = "127.0.0.1", timeout: float = 0.5) -> bool:
    """A real TCP connect. The authoritative answer to 'is anything listening?'"""
    with socket.socket() as probe:
        probe.settimeout(timeout)
        return probe.connect_ex((host, port)) == 0


def healthz(port: int, timeout: float = 2.0) -> dict:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=timeout) as r:
        return json.loads(r.read().decode())


def start_gateway(port: int, *, root: Path | str = ROOT, wait_s: float = 90.0,
                  log_path: Path | str | None = None) -> subprocess.Popen:
    """Start the gateway in its OWN process group and block until it answers.

    stdout goes to a file rather than a PIPE. An unread PIPE fills its 64 KB
    buffer and blocks the child — a hang that looks exactly like a slow start.
    """
    root = Path(root)
    log_path = Path(log_path) if log_path else root / "eval" / "out" / "gateway.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = log_path.open("w", encoding="utf-8")

    proc = subprocess.Popen(
        [sys.executable, str(root / "scripts" / "run_gateway.py")],
        env={**os.environ, "PORT": str(port)},
        stdout=log,
        stderr=subprocess.STDOUT,
        # Its own session and process group: everything it forks is ours to stop,
        # and nothing outside it is.
        start_new_session=True,
    )

    deadline = time.time() + wait_s
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(
                f"gateway exited during startup (returncode {proc.returncode}):\n"
                + log_path.read_text(encoding="utf-8")[-2000:]
            )
        try:
            healthz(port)
            return proc
        except (urllib.error.URLError, OSError, TimeoutError):
            time.sleep(0.25)

    stop_gateway(proc, port)
    raise RuntimeError(f"gateway did not answer /healthz on port {port} within {wait_s}s")


def _signal_group(proc: subprocess.Popen, sig: int) -> bool:
    """Signal the process GROUP we created. Never a pid we did not create."""
    try:
        os.killpg(os.getpgid(proc.pid), sig)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def stop_gateway(proc: subprocess.Popen, port: int, *,
                 grace: float = GRACE_SECONDS) -> dict:
    """Stop the whole group, then wait for the PORT to refuse connections.

    Returns what actually happened, so the notebook can print evidence rather
    than a reassurance.
    """
    signalled = _signal_group(proc, signal.SIGTERM)
    if not signalled:
        proc.terminate()  # the group is already gone; be sure about the child

    try:
        proc.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        pass

    escalated = False
    if port_is_open(port) or proc.poll() is None:
        # Something in the group is still holding the socket. SIGTERM asked
        # politely; SIGKILL does not ask.
        escalated = _signal_group(proc, signal.SIGKILL)
        try:
            proc.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            pass

    closed = wait_until_port_closed(port, timeout=grace)
    return {
        "returncode": proc.returncode,
        "escalated_to_sigkill": escalated,
        "port_closed": closed,
    }


def wait_until_port_closed(port: int, timeout: float = GRACE_SECONDS) -> bool:
    """Poll a real TCP connect until the port refuses. No sleeps as proof."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not port_is_open(port):
            return True
        time.sleep(0.1)
    return not port_is_open(port)
