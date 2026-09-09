# Colab final run — the only steps left

Everything else is done and green locally. This is the one piece the build
environment could not do: it has no access to Colab, and `tiktoken` could not
download its BPE table there. Five minutes of your time closes it.

---

## 1 · Create the GitHub repository and push

```bash
# from the folder containing this file
git remote add origin https://github.com/<YOUR-USERNAME>/rafid.git
git push -u origin main
```

If you were handed a `rafid.bundle` instead of the folder:

```bash
git clone rafid.bundle rafid
cd rafid
git remote set-url origin https://github.com/<YOUR-USERNAME>/rafid.git
git push -u origin main
```

The repository must be **public**, or Colab cannot clone it.

## 2 · Put the real URL in three places

Search the repo for `⟨PENDING-U3⟩` and replace every hit:

| File | What to set |
|---|---|
| `notebook/_build_notebook.py` | `REPO_URL` and the Colab badge URL |
| `README.md` | the cohort dates line |

Then rebuild the notebook and commit:

```bash
python notebook/_build_notebook.py
git commit -am "Set the repository URL and cohort dates"
git push
```

> Do **not** run `_build_notebook.py` again after step 4 — it rebuilds the
> notebook without outputs, and the outputs are the evidence.

## 3 · Open it in Colab

```
https://colab.research.google.com/github/<YOUR-USERNAME>/rafid/blob/main/notebook/capstone.ipynb
```

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

**File → Save a copy in GitHub**, same path
(`notebook/capstone.ipynb`), commit message `Phase 2: executed on Colab`.

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
