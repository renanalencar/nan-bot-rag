# AGENTS.md

Compact agent guide. `CLAUDE.md` has the long-form version of the same notes — read it before changing architecture.

## Environment

- Python 3.11+. Primary dev shell is Windows `cmd.exe` (use `.venv\Scripts\activate.bat`, not `source`).
- No test suite, no linter, no CI, no codegen. Don't invent `npm test`-style commands.
- Setup: `python -m venv .venv` → `.venv\Scripts\activate.bat` → `pip install -r requirements.txt` → `copy .env.example .env`.
- `docs/` (except `.gitkeep`) and `data/chunks/`, `data/vectorstore/` are gitignored — per-student, regenerated locally.

## Pipeline (on-disk, no in-memory chaining)

Run from repo root, in order; each phase reads the previous phase's output file:

```bat
python src/ingest.py                    :: docs/*.pdf            -> data/chunks/chunks.json
python src/embed.py                     :: chunks.json           -> data/vectorstore/ (Chroma)
python src/retrieve.py "pergunta"       :: retrieval only, no LLM call
python src/generate.py "pergunta"       :: full RAG loop, terminal
uvicorn src.main:app --reload           :: FastAPI webhooks (WhatsApp/Telegram/Slack)
```

- `ingest.py` and `embed.py` only need rerunning when `docs/` changes.
- `embed.py` recreates the Chroma collection from scratch every run — not incremental.
- `ingest.py` caches per-page raw text in `data/chunks/_raw_pages/`, so unchanged PDFs are skipped on rerun.
- Pages with fewer than `MIN_USEFUL_CHARS` (40) of embedded text are dropped silently (scanned PDFs with no text layer — no OCR in this pipeline).

## Import quirk (easy to miss)

There is **no** `src/__init__.py`. `main.py`, `generate.py`, and `generate_citations_anthropic.py` import siblings unqualified (`from llm_provider import get_provider`, `from retrieve import retrieve`) — not `from src....`. This only resolves when `src/` is on `sys.path`. `uvicorn src.main:app` from the repo root puts it there; `retrieve.py` and `generate.py` each manipulate `sys.path` themselves. Don't "fix" these to package-qualified imports without adding `__init__.py` and updating call sites.

## Constants that must stay in sync

`EMBEDDING_MODEL = "all-MiniLM-L6-v2"` and `COLLECTION_NAME = "corpus"` are duplicated as literals in `src/embed.py` and `src/retrieve.py`. Change one, change both, or retrieval silently uses a different model than the index was built with.

## Source naming (citations)

The citable "source" for a chunk is the PDF path relative to `docs/`, without extension, posix-style (e.g. `docs/regras/manual.pdf` → `"regras/manual"`). Chunk boundaries never cross pages, so `(source, p. X)` citations are unambiguous.

## LLM provider

- Selected via `LLM_PROVIDER` env var (`anthropic` | `gemini` | `openai`); each provider owns its auth env var and retry logic in `src/llm_provider.py`.
- **Extension point**: adding a provider should only touch `src/llm_provider.py` (register in `PROVIDERS`); `generate.py`/`main.py` must not change.
- `src/generate_citations_anthropic.py` deliberately bypasses the `LLMProvider` abstraction to use Anthropic's proprietary Citations API — only runs with `ANTHROPIC_API_KEY`, regardless of `LLM_PROVIDER`.

## Stale / out-of-scope files

- `ingest_ocr.py` (repo root) is a leftover from a prior D&D-rulebook POC with a hardcoded `SOURCES` list and a Tesseract dependency. Not part of the current generic pipeline (`src/ingest.py`).
- `README.md` references `bash scripts/process-new-pdfs.sh`, but no `scripts/` directory exists. Use the individual `ingest.py`/`embed.py` commands instead.

## Other

- `embed.py` has an empty `SANITY_QUERIES = []` list meant to be filled per-corpus for a manual retrieval sanity check.
