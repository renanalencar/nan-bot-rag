# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A local RAG (Retrieval-Augmented Generation) pipeline built as a teaching POC. PDFs go in `docs/`, get chunked and embedded locally, and questions are answered by an LLM citing `(source, page)`. The PDF extraction step and the LLM provider are deliberate "plug points" meant for students to extend — see the extensive Portuguese-language commentary in `README.md` ("Decisões arquiteturais" / "Como estender") before changing either.

## Setup and commands

Python 3.11+. Windows/cmd.exe is the primary dev environment (see `README.md` for exact commands).

```bat
python -m venv .venv
.venv\Scripts\activate.bat
pip install -r requirements.txt
copy .env.example .env
```

Pipeline (each phase reads the previous phase's output on disk — no in-memory chaining):

```bat
python src/ingest.py          :: docs/*.pdf -> data/chunks/chunks.json
python src/embed.py           :: chunks.json -> data/vectorstore/ (Chroma)
python src/retrieve.py "pergunta"   :: test retrieval alone, no LLM call
python src/generate.py "pergunta"   :: full RAG loop via terminal
uvicorn src.main:app --reload       :: FastAPI webhook server (WhatsApp/Telegram/Slack)
```

There is no test suite, linter, or CI config in this repo.

`ingest.py` and `embed.py` only need to be rerun when `docs/` changes. `embed.py` recreates the Chroma collection from scratch every time (not incremental).

Note: `README.md` documents a `bash scripts/process-new-pdfs.sh` convenience wrapper, but no `scripts/` directory exists in the repo — treat that section of the README as aspirational/stale, and use the individual `ingest.py`/`embed.py` commands instead.

## Architecture

Four on-disk pipeline phases plus a webhook API, each a separate script, connected only through files in `data/`:

```
docs/*.pdf → src/ingest.py → data/chunks/chunks.json → src/embed.py → data/vectorstore/ (Chroma)
                                                                            ↓
                                                              src/retrieve.py (top-k chunks)
                                                                            ↓
                                              src/generate.py (CLI) or src/main.py (webhooks) → LLM → cited answer
```

- **`src/ingest.py`** — Walks `docs/` recursively (`DOCS.rglob("*.pdf")`), extracts embedded PDF text (PyMuPDF, no OCR), chunks per-page (a chunk never spans two pages, so `(source, p. X)` citations are always unambiguous), and caches raw per-page extraction in `data/chunks/_raw_pages/` so re-running doesn't reprocess unchanged PDFs. Pages under `MIN_USEFUL_CHARS` (scanned images with no text layer) are silently dropped.
- **`src/embed.py`** — Loads `chunks.json`, computes embeddings explicitly via `sentence-transformers` (`all-MiniLM-L6-v2`, CPU, `normalize_embeddings=True`) rather than delegating to a Chroma default embedding function (kept visible on purpose, for pedagogy), and writes into a Chroma collection using cosine distance. Has an empty `SANITY_QUERIES` list meant to be filled in per-corpus for a manual retrieval sanity check.
- **`src/retrieve.py`** — Stateless query interface: embeds the question with the *same* model/params as `embed.py` and returns top-k chunks from Chroma. Designed to be imported (`retrieve(question, top_k=...)`), and separately runnable for debugging retrieval without touching any LLM.
- **`src/llm_provider.py`** — The only place that talks to LLM SDKs directly. Defines abstract `LLMProvider.generate(prompt: str) -> str`; concrete providers (`AnthropicProvider`, `GeminiProvider`, `OpenAIProvider`) each own their own auth (env var) and retry-on-transient-error logic. Selected via `LLM_PROVIDER` env var through `get_provider()`, registered in the `PROVIDERS` dict. `generate.py` and `main.py` depend only on this interface, never on a specific SDK — this is the intended extension point for adding a new provider (see README "Como estender").
- **`src/generate.py`** — Terminal entry point: `retrieve()` → build a prompt instructing the model to cite `(Source, p. X)` from context only → `get_provider().generate()`.
- **`src/main.py`** — FastAPI app exposing `/webhook` (WhatsApp Cloud API, including the GET verification-challenge route), `/telegram-webhook`, and `/slack-webhook` (including Slack's `url_verification` challenge). All three funnel into the shared `processar_pergunta_rag()` helper (retrieve → prompt → `llm.generate()`) and then push the reply back out via platform-specific send functions. Note the module-level imports (`from llm_provider import get_provider`, `from retrieve import retrieve`) are unqualified, not `from src....` — this only resolves correctly when `src/` is on the import path (as `uvicorn src.main:app` run from the repo root provides).
- **`src/generate_citations_anthropic.py`** — Alternate generation path using Anthropic's structural Citations API (model returns exact cited text + source document instead of writing citations into free text itself). Deliberately kept outside the `LLMProvider` abstraction since it's an Anthropic-only proprietary feature; only works with `ANTHROPIC_API_KEY` set, regardless of `LLM_PROVIDER`.
- **`ingest_ocr.py`** (repo root) — Leftover from a different/prior POC corpus (D&D rulebooks under `docs/Basic Rules`, `docs/SRD`, `docs/Core`, requiring a local Tesseract install) with a hardcoded `SOURCES` list. Not part of the current generic pipeline (which is `src/ingest.py`) and not wired into `docs/regimento_interno_2024.pdf` — don't assume it runs against the current corpus.

## Key conventions

- **Source naming**: the citable "source" for a chunk is the PDF's path relative to `docs/`, without extension (e.g. `docs/regras/manual.pdf` → `"regras/manual"`).
- **Embedding/retrieval model must match**: `EMBEDDING_MODEL` and `COLLECTION_NAME` are duplicated as constants in `embed.py` and `retrieve.py` — if you change one, change both.
- **`docs/` and `data/` are gitignored** (except `docs/.gitkeep`) — the corpus and derived chunks/vectorstore are per-student/local, regenerated via the pipeline, never committed.
- When adding a new LLM provider, only `src/llm_provider.py` should change; `generate.py`/`main.py` should need zero modifications.
