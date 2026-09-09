"""Build notebook/capstone.ipynb from source cells kept as plain Python.

    python notebook/_build_notebook.py

Why a builder rather than editing the .ipynb by hand: the notebook is committed
WITH its outputs, so hand-editing JSON around captured outputs invites losing
them. The cell sources live here, in a file that diffs cleanly.

Re-running this rebuilds the notebook WITHOUT outputs. Run it before executing
the notebook, never after.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "notebook" / "capstone.ipynb"

CELLS: list[tuple[str, str]] = []


def md(text: str) -> None:
    CELLS.append(("markdown", text.strip("\n")))


def code(text: str) -> None:
    CELLS.append(("code", text.strip("\n")))


# ---------------------------------------------------------------------------
md(
    """
# Rafid (رافد) — a bilingual student-services assistant

**Futun Hussain Almanqur** · SDA-AIE-213 — Large Language Model Application
Engineering (هندسة تطبيقات النماذج اللغوية الكبيرة) · SDAIA Academy

**Track B — Campus services.** Wadi University (جامعة الوادي) is fictional.

<a href="https://colab.research.google.com/github/⟨PENDING-U3⟩/blob/main/notebook/capstone.ipynb"><img src="https://colab.research.google.com/assets/colab-badge.svg" alt="Open In Colab"></a>

*Runs in Colab with no API key required by default, no manual clone, and no local
installation. The setup cell below fetches the project and starts a local backend
that answers from rules rather than from a model — so every number in this
notebook is real about this harness, and is not a claim about any provider.*
"""
)

# ---------------------------------------------------------------------------
md(
    """
## §0 · Setup — one cell

On Colab this clones the project, installs its pinned dependencies, and starts
the gateway on a free TCP port. On a machine that already has a checkout it finds
it and starts the gateway the same way.

Three things this cell refuses to paper over:

- **the tokenizer must be real.** `tiktoken` downloads its BPE table on first use.
  If that fails, this cell raises. It does not substitute an approximation,
  because every token, cache and cost number later in this notebook would then be
  measuring the substitute.
- **no provider key is used.** The cell prints whether provider key variables are
  present — as booleans, never values — and the default path does not read them.
- **the gateway must actually answer.** The cell polls `/healthz` over the socket
  and raises if it never becomes ready.
"""
)

code(
    r'''
# ── §0 setup ────────────────────────────────────────────────────────────────
import json, os, pathlib, socket, subprocess, sys, time, urllib.request

REPO_URL = "https://github.com/⟨PENDING-U3⟩"   # ← set this before running
IN_COLAB = "google.colab" in sys.modules

if "⟨PENDING-U3⟩" in REPO_URL:
    raise RuntimeError(
        "REPO_URL is not set. Put this project's GitHub URL above. "
        "The setup cell clones it; there is nothing to run without it."
    )

# ── 1. the project: cloned by this cell, not by you ─────────────────────────
if IN_COLAB:
    ROOT = pathlib.Path("/content/rafid")
    if not ROOT.exists():
        subprocess.run(["git", "clone", "--depth", "1", REPO_URL, str(ROOT)], check=True)
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-q",
         "-r", str(ROOT / "gateway" / "requirements.txt"),
         "-r", str(ROOT / "requirements.lock")],
        check=True,
    )
else:
    ROOT = pathlib.Path.cwd()
    while not (ROOT / "gateway").exists() and ROOT != ROOT.parent:
        ROOT = ROOT.parent
    if not (ROOT / "gateway").exists():
        raise RuntimeError("run this from inside a checkout of the project")

sys.path.insert(0, str(ROOT / "gateway"))
os.chdir(ROOT)
print("project root :", ROOT)

# ── 2. secrets: presence only, never values ─────────────────────────────────
for _var in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "RAFID_PRIMARY_API_KEY"):
    print(f"{_var}_PRESENT={bool(os.environ.get(_var))}")
print("the default path below uses none of them")

# ── 3. the tokenizer must be real ───────────────────────────────────────────
import tiktoken

try:
    _enc = tiktoken.get_encoding("o200k_base")
    _probe = _enc.encode("كم رسوم إصدار السجل الأكاديمي؟")
except Exception as exc:
    raise RuntimeError(
        "tiktoken could not load its BPE table, so token, cache and cost numbers "
        "in this notebook would be measuring a substitute. Stopping instead. "
        f"Underlying error: {exc}"
    ) from exc
print(f"TOKENIZER=REAL  encoding={_enc.name}  probe_tokens={len(_probe)}")

# ── 4. a free port, so a re-run does not collide with the last run ──────────
if not os.environ.get("RAFID_GATEWAY_PORT"):
    with socket.socket() as _probe_sock:
        _probe_sock.bind(("127.0.0.1", 0))
        os.environ["RAFID_GATEWAY_PORT"] = str(_probe_sock.getsockname()[1])
PORT = int(os.environ["RAFID_GATEWAY_PORT"])
BASE = f"http://127.0.0.1:{PORT}"

# every route points at the local gateway; a real provider is two env vars away
for _route in ("PRIMARY", "CHEAP", "COMPARISON", "ONPREM"):
    os.environ[f"RAFID_{_route}_BASE_URL"] = f"{BASE}/v1"
os.environ.setdefault("MOCKGW_SPEED", "0.2")


# ── 5. start it over a real TCP socket, and wait until it answers ───────────
def get(path, timeout=5):
    with urllib.request.urlopen(f"{BASE}{path}", timeout=timeout) as r:
        return json.loads(r.read().decode())


def post(path, payload, timeout=60):
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(payload).encode(),
        headers={"content-type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def start_gateway(wait_s=90):
    """Start the vendored gateway and block until /healthz answers."""
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "scripts" / "run_gateway.py")],
        env={**os.environ, "PORT": str(PORT)},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    deadline = time.time() + wait_s
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError("gateway exited during startup:\n" + proc.stdout.read())
        try:
            get("/healthz", timeout=2)
            return proc
        except Exception:
            time.sleep(1)
    proc.terminate()
    raise RuntimeError(f"gateway did not answer /healthz within {wait_s}s")


GATEWAY = start_gateway()

print()
print("port         :", PORT)
print("pid          :", GATEWAY.pid, "· poll() =", GATEWAY.poll(), "(None means running)")
print("GET /healthz :", get("/healthz"))
print("GET /v1/models:", [m["id"] for m in get("/v1/models")["data"]])
'''
)

# ---------------------------------------------------------------------------
md(
    """
### §0.1 · The service directory

Twelve fictional Wadi University services. This file is the ground truth for
every grounded answer below: a fee that is not in it cannot appear in an answer,
and the evaluation harness later asserts exactly that.

The renderer here is temporary scaffolding for the setup proof. The domain module
that owns it properly arrives in phase 6, and the versioned prompt artefacts in
phase 7.
"""
)

code(
    r'''
import yaml

SPEC = yaml.safe_load((ROOT / "data" / "service_directory.yaml").read_text(encoding="utf-8"))

INSTRUCTION = (
    "You are a student services assistant for Wadi University. Answer only from "
    "the service directory below. If the answer is not in the directory, say you "
    "do not know and point the student to the registrar."
)


def render_directory(language="en"):
    """Render the YAML into the block format the gateway parses out of a prompt."""
    ar = language == "ar"

    def k(base):
        return f"{base}_ar" if ar else base

    lines = [f"registrar_contact: {SPEC[k('registrar_contact')]}", ""]
    for e in SPEC["entries"]:
        lines += [
            f"### {e['id']} — {e['title_ar'] if ar else e['title_en']}",
            f"- service_type: {e['service_type']}",
            f"- fee: {e[k('fee')]}",
            f"- processing_time: {e[k('processing_time')]}",
            "- documents: " + "; ".join(e[k("documents")]),
            "- steps: " + " | ".join(e[k("steps")]),
            "- keywords: " + ", ".join(e["keywords"]),
            "",
        ]
    return "\n".join(lines)


def system_prompt(language="en"):
    return f"{INSTRUCTION}\n\n<service_directory>\n{render_directory(language)}\n</service_directory>"


def ask(question, language="en", model="course-flagship"):
    return post("/v1/chat/completions", {
        "model": model,
        "max_tokens": 400,
        "messages": [
            {"role": "system", "content": system_prompt(language)},
            {"role": "user", "content": f"<student_message>{question}</student_message>"},
        ],
    })


print(f"{len(SPEC['entries'])} services · types: {SPEC['service_types']}")
print(f"campuses: {SPEC['campuses']}")
print(f"directory renders to {len(render_directory('en'))} characters (en), "
      f"{len(render_directory('ar'))} (ar)")
'''
)

# ---------------------------------------------------------------------------
md(
    """
### §0.2 · One request through the socket

Not an in-process call: a real `POST /v1/chat/completions` over TCP to the port
above, carrying the directory in the system prompt.
"""
)

code(
    r'''
r = ask("How much does an official academic transcript cost?")
print("model :", r["model"])
print("usage :", json.dumps(r["usage"], ensure_ascii=False))
print("finish:", r["choices"][0]["finish_reason"])
print()
print(r["choices"][0]["message"]["content"])
'''
)

# ---------------------------------------------------------------------------
md(
    """
### §0.3 · Bilingual smoke test

The same question in both languages. Both must return the directory's value —
`SAR 60 per copy` / `٦٠ ريالاً لكل نسخة` — and the assertions below fail the cell
if either does not.
"""
)

code(
    r'''
en = ask("How much does an official academic transcript cost?")["choices"][0]["message"]["content"]
ar = ask("كم رسوم إصدار السجل الأكاديمي؟", language="ar")["choices"][0]["message"]["content"]

print("EN ─────────────────────────────────────────────────────────────────")
print(en)
print()
print("AR ─────────────────────────────────────────────────────────────────")
print(ar)
print()

assert "SAR 60 per copy" in en, "the English answer did not quote the directory fee"
assert "٦٠" in ar, "the Arabic answer did not quote the directory fee"
print("PASS  both languages quote data/service_directory.yaml → transcript_request")
'''
)

# ---------------------------------------------------------------------------
md(
    """
### §0.4 · Restart proof

Terminate the gateway, confirm it is gone, then start it again **with the same
`start_gateway()` this cell's setup defined** and confirm it answers. This is what
separates "it works" from "it happens to still be running from an earlier
attempt".
"""
)

code(
    r'''
GATEWAY.terminate()
GATEWAY.wait(timeout=20)
print("terminated   : returncode =", GATEWAY.returncode)

try:
    get("/healthz", timeout=2)
    raise AssertionError("something is still answering on the port — restart proves nothing")
except AssertionError:
    raise
except Exception as exc:
    print("port is dead  :", type(exc).__name__)

GATEWAY = start_gateway()
print("restarted    : pid =", GATEWAY.pid, "· poll() =", GATEWAY.poll())
print("GET /healthz :", get("/healthz"))

again = ask("How much does an official academic transcript cost?")
text = again["choices"][0]["message"]["content"]
assert "SAR 60 per copy" in text, "the restarted gateway did not answer from the directory"
print("PASS  a fresh process answers from the directory — no leftover state")
'''
)


def main() -> None:
    nb = {
        "cells": [
            {
                "cell_type": kind,
                "metadata": {},
                "source": source.splitlines(keepends=True),
                **({"outputs": [], "execution_count": None} if kind == "code" else {}),
            }
            for kind, source in CELLS
        ],
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.11"},
            "colab": {"provenance": []},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    OUT.write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} — {len(CELLS)} cells, outputs empty")


if __name__ == "__main__":
    main()
