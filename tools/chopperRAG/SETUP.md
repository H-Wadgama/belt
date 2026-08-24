# chopperRAG — step-by-step run guide

Cheat sheet for running the separation-heuristics RAG PoC from a cold start
(new Anaconda Prompt window, Ollama not yet confirmed running). See
`README.md` for what the tool does and design notes; this file is just the
"what do I type" checklist.

## 0. One-time setup (skip if already done)

```bash
conda activate pyfuel
cd "tools/chopperRAG"
pip install -r requirements.txt
```

Pull the Qwen model once (large download, only needed the first time or
after switching models):

```bash
ollama pull qwen3:8b
```

## 1. Every session — activate + navigate

Open Anaconda Prompt:

```bash
conda activate pyfuel
cd "C:\Users\hwadg\OneDrive - The Pennsylvania State University\Shi_Wadgama_shared\Models\ATJSPK\tools\chopperRAG"
```

## 2. Make sure Ollama is up and has the model

Ollama installs as a background service on Windows, so it's usually already
running. Confirm with:

```bash
ollama list
```

- If this prints a table (with `qwen3:8b` in it) — you're set, skip ahead.
- If you get a connection error, the service isn't running: start it with
  `ollama serve` in its own terminal window (leave that window open), or
  just relaunch the Ollama app from the Start menu.
- If `qwen3:8b` isn't in the list, pull it: `ollama pull qwen3:8b`.

You do **not** need to run `ollama run qwen3:8b` — that opens an interactive
chat session, which isn't what `query.py` uses. `query.py`/`seed_heuristics.py`
talk to the background server directly over HTTP; the model loads into
memory automatically on the first request.

## 3. Load heuristics into the vector store

Only needed when `seed_heuristics.py`'s `SEED_HEURISTICS` list has changed
(new heuristic added/edited). This step doesn't need Ollama — it only uses
the local embedding model (`sentence-transformers`) and Chroma.

```bash
python seed_heuristics.py
```

It prints one `seeded: [...]` line per heuristic. Upserts by ID, so it's
safe to re-run any time — re-running with unchanged heuristics just
overwrites the same records.

## 4. Query

Ad hoc question:

```bash
python query.py "My feed has a corrosive component - where in the separation sequence should I remove it?"
```

Or run the three canned PoC questions:

```bash
python query.py --test
```

Each run prints, per question:
- the retrieved heuristics as JSON, **ordered nearest-first**, each with a
  `distance` field (Chroma L2 distance — lower means more similar; this is
  the "similarity score" — the print order already reflects the ranking)
- the retrieved raw textbook chunks
- `ANSWER:` — Qwen's prose answer grounded in the above (this is the step
  that needs Ollama actually running; steps 1–3 above don't)

## Quick troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `ConnectionError` / refused on `query.py`'s `ANSWER:` step | Ollama server not running | `ollama serve`, or relaunch the Ollama app |
| Ollama error mentioning the model isn't found | `qwen3:8b` never pulled | `ollama pull qwen3:8b` |
| `ModuleNotFoundError` | Wrong/no conda env active, or deps not installed | `conda activate pyfuel`, then `pip install -r requirements.txt` in this folder |
| New heuristic doesn't show up in `query.py` results | Forgot to re-run seeding after editing `seed_heuristics.py` | `python seed_heuristics.py` |
