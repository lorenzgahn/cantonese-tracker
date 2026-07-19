# Cantonese Dialogue Tracker

A personal, local-only app that automates a manual Cantonese study workflow:
extract jyutping from a dialogue transcript, segment it into words, define
the ones you don't know, and track each word's status (`known` /
`learning` / `learned`) **globally across every dialogue you've studied** —
not per-document. Full product spec: [SPEC.md](SPEC.md).

It replaces a previous by-hand process of copying jyutping into a doc,
highlighting unknown words in red, bracketing multi-syllable words, and
pasting into ChatGPT for definitions.

## Stack

- **Backend**: Python 3.11, FastAPI, Pydantic v2, `pdfplumber` (PDF import),
  `pycantonese` (segmentation), `anthropic` SDK (LLM fallback for
  definitions/segmentation).
- **Frontend**: React 18 + TypeScript + Vite, React Router. No state
  library — plain component state.
- **Storage**: flat JSON files under `backend/data/` (no database).

## Setup

### Backend

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

**LLM auth** (needed for definition lookups and import-time segmentation
cleanup): install the [Anthropic CLI](https://github.com/anthropics/anthropic-cli)
and run `ant auth login`. This authenticates via OAuth against your
claude.ai account — no `ANTHROPIC_API_KEY` needed — but note that raw API
calls bill against a **separate pay-as-you-go credit balance** at
console.anthropic.com, not a claude.ai Pro/Max chat subscription. Add
credits there if you see `BadRequestError: credit balance too low`.

**Dictionary data**: `backend/data/dictionary.json` is built once from
CC-Canto/CC-CEDICT source files via `backend/etl/build_dictionary.py`. It's
already checked in under `backend/data/`; only re-run the ETL script if you
need to refresh it from `backend/etl/downloads/`.

### Frontend

```bash
cd frontend
npm install
```

## Running

Two dev servers, both with hot reload:

```bash
# backend — from backend/, with .venv activated
uvicorn app.main:app --reload --port 8000

# frontend — from frontend/
npm run dev
```

Frontend expects the backend at `http://localhost:8000` (hardcoded in
`frontend/src/api/client.ts`). Open the Vite dev server URL (usually
`http://localhost:5173`).

## Testing

```bash
cd backend
source .venv/bin/activate
python -m pytest -q                    # full suite
pytest tests/test_vocab_store_lifecycle.py -q         # one file
pytest tests/test_vocab_store_lifecycle.py::test_on_click_always_learning -q  # one test
```

```bash
cd frontend
npx tsc --noEmit   # typecheck
npm run build      # typecheck + production build
```

There is no frontend test suite (component behavior is verified live in a
browser, not with a JS test runner).
