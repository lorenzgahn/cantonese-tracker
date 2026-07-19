# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

**Backend** (from `backend/`, with `.venv` activated — `source .venv/bin/activate`):

```bash
python -m pytest -q                                            # full suite
pytest tests/test_vocab_store_lifecycle.py -q                  # one file
pytest tests/test_vocab_store_lifecycle.py::test_on_click_always_learning -q  # one test
uvicorn app.main:app --reload --port 8000                      # dev server
```

**Frontend** (from `frontend/`):

```bash
npx tsc --noEmit    # typecheck only
npm run build       # typecheck + production build
npm run dev          # dev server (Vite, port 5173)
```

No frontend test suite exists — UI behavior is verified live in a browser (see `<preview_tools>` workflow), not with a JS test runner. No lint config in either half of the repo.

Not a git repository — there's no `.git` at the project root.

## Architecture

### The data model split is the load-bearing idea in this codebase

`backend/app/models/dialogue.py` defines two parallel shapes for everything:

- `StoredWordToken` / `StoredLine` / `StoredDialogue` — the immutable, structural form persisted to `data/dialogues/<id>.json` at import time. Carries **no** status or definition.
- `WordToken` / `Line` / `Dialogue` — the API/frontend-facing form, denormalized with each word's *current* vocab status at **read time**.

`dialogue_store.join_with_vocab()` is where the join happens: it loads `vocab_store`'s global `{word_id: VocabEntry}` map and stamps each token's live status/definition onto the stored structure fresh, every single read. Nothing about a word's learning status is ever baked into a dialogue file.

**Why this matters**: vocab status is keyed by `word_id` (normalized jyutping) globally, not per-dialogue. Click a word while reviewing dialogue A, and it shows up already flagged in dialogue B the next time you open it — with zero extra code, because both dialogues resolve the same `word_id` against the same central store on every load. Any change to how status is read or written should go through `vocab_store.py`, never by mutating a `StoredDialogue` directly (the one exception is `dialogue_store.merge_adjacent_tokens`, which intentionally rewrites token *structure*, not status, to fix bad segmentation).

**Definition is the one exception to "everything is global"**: the same jyutping can mean different things in different dialogues (a homophone, a different sense in context), so `StoredDialogue.definition_overrides` (`dict[word_id, str]`) holds per-dialogue definition overrides. `join_with_vocab` prefers a dialogue's own override over the global `vocab_store` default whenever one is set, dialogue by dialogue — status is unaffected and stays fully global either way. Set via `dialogue_store.set_definition_override()` / `POST /{dialogue_id}/words/{word_id}/definition` (this is what the Review page's "edit definition" button now calls, no longer the global `PUT /api/vocab/{word_id}`). `reevaluate_word` is override-aware too: it refreshes the dialogue's override if one exists for that word, otherwise the global default — so a document-specific correction doesn't silently get clobbered by re-evaluating in a different dialogue. There's no "clear override" endpoint yet; reverting one currently means editing the dialogue's JSON file directly.

**`word_id` folds in hanzi, not just jyutping**: the same jyutping can be two completely unrelated words (`teng1` 聽 "listen" vs `teng1` 廳 "living room"), not just a difference in sense — so `word_id` (the key everything above is keyed by: status, definitions, click/unclick, bullet dedup) is computed by `jyutping_utils.compute_word_id(jyutping, hanzi)`, not `normalize_jyutping_key` directly. When hanzi is known it's folded in (`f"{key}__{hanzi}"`), giving each sense fully independent status/definition/flagging, both within one dialogue and across all of them — with zero extra plumbing, since everything downstream just treats word_id as an opaque string. Falls back to jyutping alone when hanzi is unknown (plain-jyutping/legacy-annotated imports have no hanzi at all, so same-sounding words there are genuinely indistinguishable — this is a real, accepted limitation of those two input types, not a bug). Every `StoredWordToken.word_id` assignment site (all 4 importers, plus `merge_adjacent_tokens`/`split_token`/`edit_token_jyutping` in `dialogue_store.py`) goes through `compute_word_id` — `edit_token_jyutping` deliberately passes `hanzi=None` since it clears the token's hanzi (see above), so a corrected reading's word_id is jyutping-only until re-imported or re-merged. **Existing dialogues on disk keep their old jyutping-only word_id** for tokens untouched since this changed — only new imports, and any token that goes through merge/split/edit-jyutping, get sense-aware ids going forward. There's no bulk migration for already-imported dialogues; re-import if separating an existing homophone collision matters.

### Four import pipelines, one shared segmentation core

`backend/app/services/importers/` holds one importer per input type (`plain_jyutping.py`, `legacy_annotated.py`, `hanzi_narrative.py`; the fourth, structured PDF, lives one level up at `backend/app/services/pdf_parser.py`, not inside `importers/`). `detector.py` auto-classifies pasted/uploaded text into one of the four; the Import page always shows a manual override since none of the heuristics are airtight.

All non-trivial word-boundary logic funnels through `segmentation.py`:
- `segment_hanzi()` wraps `pycantonese.segment()`, post-processed to split out embedded punctuation pycantonese sometimes glues onto a token.
- `is_suspicious_merge()` flags a segmented word ≥3 chars with no whole-word dictionary hit as a likely bad merge (pycantonese has a real, observed tendency to glue an unfamiliar word onto its neighbor) — these get routed to the LLM reconciliation pass instead of being trusted.
- `project_hanzi_to_jyutping()` (Type 1, jyutping already exists — align it to hanzi word boundaries) and `segment_jyutping_trie()` (Type 2, no hanzi — longest-match against the CC-Canto dictionary) are the two alignment strategies.

Each importer keeps a pure `build_stored_dialogue()` (no I/O, no LLM, fully unit-testable) separate from the public `import_*()` entry point, which additionally runs LLM reconciliation over anything the pure pass flagged. **This split is deliberate — do not add LLM calls inside a `build_stored_dialogue()`.**

### LLM integration (`services/llm.py`, `services/definitions.py`)

Auth is via `ant auth login` (OAuth against the user's claude.ai account) — `anthropic.Anthropic()` picks this up automatically, no `ANTHROPIC_API_KEY` needed. **Important billing gotcha**: this OAuth login only proves identity; raw API calls still bill against a separate pay-as-you-go credit balance at console.anthropic.com, *not* a claude.ai Pro/Max subscription. `ANTHROPIC_MODEL` in `app/config.py` is deliberately set to `claude-sonnet-5`, not Opus, for cost — don't change this without discussing it, since it was a deliberate downgrade after a real cost surprise.

Three call sites, three different caching disciplines:
- `definitions.resolve_definition()` — dictionary-first, LLM fallback; called lazily, only when a word is actually clicked and has no cached definition yet.
- `generate_jyutping_batch()` / `validate_segmentation_batch()` — batched *per dialogue*, not per word/line, called once from each importer's reconciliation pass over everything the pure pass flagged.
- All three degrade gracefully on LLM failure (falls back to a placeholder / leaves existing state alone) rather than failing the whole import or click — see the `try/except` pattern already used in each call site and follow it for new ones.

**Any test that exercises an importer's public `import_*()` entry point (not just `build_stored_dialogue()`) or the `click_word`/`reevaluate_word` review endpoints will hit the real network unless the relevant `llm.py` function is explicitly monkeypatched.** Every existing test file that needs this has an autouse fixture stubbing the exact functions it calls (see `tests/test_hanzi_narrative_importer.py` and `tests/test_pdf_parser.py` for the pattern) — a missing stub here is a real, billed API call, not just a slow test; it's happened twice in this repo's history and both times showed up as an anomalously slow (tens-of-seconds) `pytest` run.

### Frontend: one token array is the single source of truth

`ReviewPage.tsx` holds one `dialogue.lines[].words[]` structure in state. The inline word span, the per-line bullet list, and the dialogue-aggregate bullet list are all *derived views* (`.filter()`) of that same array — not separate copies kept in sync by hand. Every mutating action (click/unclick/re-evaluate/merge) POSTs, gets back the authoritative new state from the server, and folds it back into this one array (`applyEntry` for status/definition patches; `mergeWithNext` replaces the whole dialogue since token structure — not just a field — changes). Follow this pattern for new interactions rather than introducing parallel state.

UI conventions worth preserving (explicit user preferences, not defaults): no Chinese characters are ever rendered in the frontend — jyutping only; the theme is a fixed soft-ivory light theme with no dark-mode media query (removed deliberately); bullet-list entries are always `**word** — definition` on one line, never split across lines.

## Local dev environment notes

- Dev servers (`uvicorn`, `vite`) are **not daemonized** across sessions — they die when the enclosing session/terminal does. Before assuming the app is running, check (`curl localhost:8000/api/health`, `curl -o /dev/null -w "%{http_code}" localhost:5173`) rather than trusting a previous turn's state.
- The `.claude/launch.json` used by the preview/browser tooling lives at the **parent** directory (one level above this project root), not inside `cantonese-tracker/` — check there first if `preview_start` can't find a named config.
