# Colab final run — the only steps left

Everything else is done and green locally. This is the one piece the build
environment could not do: it has no access to Colab, and `tiktoken` could not
download its BPE table there. Five minutes of your time closes it.

---

## 1 · Create the GitHub repository and push

```bash
git clone rafid.bundle rafid
cd rafid
git remote add origin https://github.com/Futun-Almanqur/rafid.git
git push -u origin main
```

If you already have the folder rather than the bundle, skip the clone and start
at `git remote add`.

The repository must be **public**, or Colab cannot clone it.

## 2 · Nothing to fill in

The repository URL and the cohort dates are already set:

| Setting | Value |
|---|---|
| `REPO_URL` in the setup cell | `https://github.com/Futun-Almanqur/rafid` |
| Colab badge | points at `Futun-Almanqur/rafid`, branch `main` |
| Cohort dates in `README.md` | 6 September 2026 – 9 September 2026 |

> Do **not** run `notebook/_build_notebook.py` after step 4 — it rebuilds the
> notebook without outputs, and the outputs are the evidence.

## 3 · Open it in Colab

```
https://colab.research.google.com/github/Futun-Almanqur/rafid/blob/main/notebook/capstone.ipynb
```

Or click the badge at the top of the README.

## 4 · Clean runtime, then run everything

1. **Runtime → Disconnect and delete runtime**
2. Reconnect
3. **Runtime → Run all**

A clean runtime is the point. A notebook that only runs because of leftover state
is the most common way to lose Section 7.

## 5 · What must be green

| Cell | Must show |
|---|---|
| §0 setup | `OPENAI_API_KEY_PRESENT=False` and `ANTHROPIC_API_KEY_PRESENT=False` |
| §0 setup | **`TOKENIZER=REAL  encoding=o200k_base`** |
| §0 setup | a port number, a pid, `poll() = None` |
| §0 setup | `GET /healthz` returning `ok: True` and `tokenizer: REAL` |
| §0 setup | `GET /v1/models` listing four models incl. `wadi-onprem` |
| §0.2 | a real `usage` block and a grounded English answer |
| §0.3 | both languages, then `PASS both languages quote…` |
| §0.4 | `terminated`, `port is dead`, `restarted`, then `PASS a fresh process…` |

**If `TOKENIZER=REAL` does not appear, stop.** The cell is written to raise
rather than substitute an approximation. Send me the traceback — that failure is
a real finding, not something to work around.

## 6 · Save the executed notebook

**File → Save a copy in GitHub** → repository `Futun-Almanqur/rafid`, branch
`main`, path `notebook/capstone.ipynb`, commit message
`Phase 2: executed on Colab`.

Or: **File → Download → Download .ipynb** and send me the file.

## 7 · Send back

Either the pushed commit hash, or the downloaded `capstone.ipynb`.

I will then:

- read the real outputs and fill in the Phase 2 verdict from them;
- mark ADR 004's tokenizer issue **RESOLVED ON TARGET PLATFORM** if the real
  tokenizer loaded, or leave it OPEN if it did not;
- re-run `eval/report.py` so `EVALUATION_REPORT.md` and `BENCHMARKS.md` carry
  `LOCAL VERIFIED` instead of `COLAB VERIFICATION PENDING` on the cost rows;
- commit that as the final phase.

---

## If something fails

Send me the traceback rather than fixing it. Two failures would be genuinely
informative:

- **`tiktoken` cannot download** — then the zero-setup claim has a dependency we
  need to state, and I will vendor the BPE table.
- **the gateway never answers `/healthz`** — `scripts/run_gateway.py` has never
  served a request anywhere, so this is its first real run.
