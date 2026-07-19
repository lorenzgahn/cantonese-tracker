# Cantonese Dialogue Tracker — Spec (v1 draft)

## 1. Problem & goal

Today the workflow is manual: read a dialogue transcript (e.g. the "Cantonese
Conversations" PDF series), copy the jyutping into a doc, highlight unknown
words in red, group multi-syllable words with `[...]`, paste into ChatGPT to
get definitions, and keep the definitions as a trailing list. This is slow
and the vocab learned never accumulates anywhere durable.

Goal: a local app that automates extraction + lookup, turns "click a word"
into the highlighting step, and keeps a persistent, queryable record of
every word encountered and its status (known / learning / learned) over
time — across all dialogues studied.

Anki export is a named future goal but is **spec-only** in this doc (§8) —
not built in v1.

## 2. Non-goals (v1)

- Anki card generation (spec'd, not implemented)
- Multi-user / auth / cloud sync
- Mobile app
- Audio playback/alignment
- Perfect automatic word segmentation — the UI must let the user
  merge/split word boundaries by hand when segmentation gets it wrong

## 3. Inputs the app must handle

1. **Structured table-format PDF** (the type attached: "Cantonese
   Conversations" by Olly Richards, and likely similar books in the same
   series). Each dialogue line is a table row block of: speaker name → hanzi
   line → jyutping line → English line. The doc also ends with an appendix
   vocabulary list (a curated subset, not exhaustive — useful as a seed for
   definitions but not authoritative).
2. **Plain pasted jyutping text** with no hanzi (no structure to lean on).
3. **Legacy already-annotated text** — the format the user has already been
   producing by hand (jyutping with `[bracketed]` compounds + a trailing
   `word: definition` list). Importing this should backfill history rather
   than being thrown away.
4. **Hanzi-only narrative text** — no jyutping, no English, no speaker
   structure. Typically a children's-book-style story: numbered scene
   markers (`[0]`, `[2]`, ...) delimiting paragraphs of narration with
   embedded `「...」` dialogue, rather than turn-based speaker exchanges.
   Each `[N]`-block becomes one `Line` with `speaker: null`. This format
   needs jyutping *generated*, not extracted — see §4 Step 1a.

The importer auto-detects which of these it's looking at, with a manual
override if detection guesses wrong.

## 4. Pipeline

### Step 1 — Extract clean jyutping doc

Parse the input into a `Dialogue` made of ordered `Line`s (speaker +
jyutping text, hanzi/English retained internally but not required for
display). Output a speaker-labelled, jyutping-only document, exportable as
`.md`/`.txt` — this is the artifact the user currently builds by hand before
even opening ChatGPT.

### Step 1a — Generate jyutping for hanzi-only input (type 4)

No new dictionary needed — every CC-Canto entry is already keyed
`hanzi → jyutping` (§6), the lookup just needs to also return that field
instead of using it only internally.

1. Segment each `[N]`-block's hanzi with the same `pycantonese.segment()`
   used in Step 2 below (reused, not duplicated).
2. Look up each segmented word's jyutping in the CC-Canto index — this
   reconstructs the jyutping line that other input types already have,
   turning §4 Step 1 into a generation step for this format rather than an
   extraction step.
3. Words the dictionary misses fall through to the same LLM validation
   pass as Step 2's segmentation misses (below) — same call, also asked to
   supply jyutping for that span.

**Caveat**: Cantonese has some polyphony — a handful of characters (`得`,
`平`, `重`, ...) read differently depending on context. Word-level lookup
(not character-by-character) resolves most of this, since compounds
usually have one canonical reading in CC-Canto; a standalone character
with a genuinely ambiguous reading is the residual weak spot, and is
exactly what the LLM validation pass exists to catch — not new machinery,
just another trigger condition for it. A dedicated hanzi→jyutping package
(`ToJyutping`, from CanCLID/Jyutping.org) is worth evaluating later if
accuracy on this input type matters more than reusing the CC-Canto index —
flagging as a build-time choice, not committing to it now.

### Step 2 — Segment each line into words

Word boundaries aren't marked in jyutping (space = syllable, not word), so
segmentation quality depends on what's available:

- **When hanzi is available** (structured PDF case): run Cantonese word
  segmentation on the **hanzi** line (`pycantonese.segment()`, which uses a
  jieba-style maximum-matching tokenizer seeded largely from HKCanCor — a
  corpus of *transcribed spoken* Cantonese, so better matched to
  conversational register than a generic written-Chinese segmenter). Since
  each hanzi character corresponds 1:1 to one jyutping syllable in these
  transcripts, project the hanzi word boundaries back onto the jyutping
  syllable sequence to get word-level (jyutping, hanzi) pairs directly.
- **When only jyutping is available** (plain-text case): longest-match
  segmentation against a jyutping-keyed dictionary trie (built from
  CC-Canto data — see §6).

**Known weak spots, called out honestly**: dictionary/corpus-based
segmentation will reliably struggle with code-switched English tokens
(`keep`, `po`, `shopping`, `Instagram`), proper nouns (`狗牙嶺`, `東涌`),
and colloquial slang compounds not in the corpus (`咧啡`, `喪`) — exactly
the kind of thing that shows up constantly in this material. Rather than
treating the LLM as a rare fallback, it's a **first-class validation
pass**: dictionary segmentation runs first (fast, free), but any line
containing Latin-script tokens, or any span the dictionary can't match at
all, gets sent to the LLM to re-segment/confirm before being shown.

Segmentation output is always editable in the UI — click-drag or
click-to-merge/split on the syllable spans — this is a real, expected
feature here, not just an edge-case safety net.

### Step 3 — Define words, but only the ones that need it

Definitions are **not** fetched eagerly for every segmented word — only for
words that are actually unknown, which keeps the review screen uncluttered
and avoids paying for dictionary/LLM lookups on words you already know.
Each segmented word is first cross-referenced against the vocab store:

- Store status `known` or `learned` → render as plain inline text, no
  lookup, not bulleted, no definition shown.
- Store status `learning` (already flagged in an earlier dialogue) →
  render highlighted red, definition already cached from before, included
  in the bullet lists automatically.
- Not in the store at all (brand new word) → render as plain clickable
  text, **not** bulleted or defined yet, on the assumption it's known
  (per your rule below) — until clicked.

A definition is resolved (dictionary first, LLM fallback for
misses/contextual sense — see §6) at the moment a word is **clicked**,
i.e. exactly when it's flagged unknown and needs to actually show up in a
list.

1. Look up in the local **CC-Canto dictionary** (bundled, offline, free,
   keyed by hanzi + jyutping) — primary source, no API cost.
2. If not found, or the sense needed is contextual/idiomatic/slang (common
   here — e.g. `waa6 saai3`, `gam3 le5 fe5`), fall back to an **LLM call**
   (Claude) with the surrounding line as context, matching the gloss style
   you already get from ChatGPT (short, plain-English, learner-oriented).
3. Cache the resolved definition on the `VocabEntry` so it's never looked
   up twice.

### Step 4 — Review (the "highlighting" step)

The dialogue renders with every word as a clickable inline span. Known/
learned words show as plain text with no inline gloss — clicking a word
resolves its definition (Step 3) and adds it to two lists, so **only
unknown words ever get defined or bulleted**:

- a **per-line bullet list** of that line's flagged-unknown words +
  definitions directly underneath it (mirrors the structure you
  described — lists nested under each paragraph where the words appear)
- an **aggregate per-dialogue bullet list** at the end (deduped union of
  all flagged-unknown words in the dialogue)

Clicking a word (inline **or** in either bullet list — both are the same
underlying token, so they stay in sync) toggles it red and flags it
`learning`. Everything left unclicked when the user hits **Finish Review**
is committed as `known` — per your rule, *unmarked = already known at the
time the dialogue was processed*, including words never seen before.

Re-visiting an already-reviewed dialogue later does not reset previously
committed statuses just by viewing it again.

## 5. Data model

Status lifecycle for a word, tracked **globally**, not per-dialogue:

```
new (not yet in store)
  └─ on first review, unclicked → known
  └─ on first review, clicked   → learning
learning ──(manually promoted, once you feel solid on it)──> learned
known / learning / learned ──(clicked again in a later dialogue)──> learning
```

Clicking a word always means "flag/keep this as something I'm still
studying" — so it can pull an already-`known` word back into `learning` if
it turns out you didn't actually remember it, or reinforce an existing
`learning` word.

**`VocabEntry`**
| field | notes |
|---|---|
| id | canonical key, normalized jyutping (tone-marked) |
| hanzi | if known |
| definition | current gloss |
| source_of_definition | `dictionary` \| `llm` \| `manual` (legacy import) |
| status | `known` \| `learning` \| `learned` |
| first_seen_dialogue_id / date | |
| last_seen_date | |
| times_seen | occurrence count, used to prioritize study |
| occurrences[] | `{dialogue_id, line_id, snippet}` — traceability + future Anki source sentences |
| user_notes | optional free text |

**`Dialogue`** → ordered `Line`s → ordered `WordToken`s (span into the line
text + ref to a `VocabEntry`).

## 6. Storage & dictionary integration (v1)

Per your ask, start file-based, no server DB:

- `data/dialogues/<dialogue-id>.json` — parsed dialogue, lines, tokens
- `data/vocab_store.json` — the single running array of `VocabEntry`,
  this is *the* progress-tracking file

**CC-Canto isn't an API — it's a flat text file, indexed once, offline:**

1. One-time setup script downloads `cccanto-webdist.txt` + the CC-CEDICT
   Cantonese-readings file from cantonese.org (CC BY-SA — fine for personal
   use, attribute if ever redistributed).
2. Each line (`traditional simplified [jyutping] /def1/def2/`) is parsed
   with a regex into records.
3. Two indexes are built: hanzi → entries, and normalized jyutping (spaces
   stripped, e.g. `faan1zo2`) → entries. Hanzi lookup is preferred when
   available, since jyutping alone is ambiguous across homophones.
4. The whole dataset is only a few MB, so it's preprocessed once into
   `data/dictionary.json` (or `.pkl` for faster load) and loaded fully into
   memory at FastAPI startup — no need for a query engine over static
   reference data.
5. Runtime lookup is a single function: `lookup(hanzi=None,
   jyutping=None)` — checks the hanzi index first, falls back to the
   jyutping index, and if nothing matches, that miss is what triggers the
   LLM fallback (§4, Step 3).

`words.hk` has better modern slang/colloquial coverage but is treated as a
Phase-2 maybe, not v1 — bulk-redistribution licensing for its data isn't as
clearly established as CC-Canto's, so if added later it'd be live per-word
API calls (rate-limited, cached locally) rather than a bulk import.

`vocab_store.json` being plain JSON (rather than SQLite) keeps it
git-friendly/diffable if you ever want to version your own progress. If
querying it gets slow or the query needs get richer (e.g. "learning words
seen 3+ times, not reviewed in 2 weeks"), migrating just that one file to
SQLite later is a small, isolated change — flagging as an explicit
non-decision now rather than a v1 requirement.

## 7. UI screens

1. **Import** — upload PDF or paste text; mode auto-detected (structured
   PDF / plain jyutping / legacy annotated) with manual override.
2. **Extracted doc view** — the clean jyutping-only output of Step 1, with
   export to `.md`/`.txt`.
3. **Review** (core screen) — Step 4 above: clickable inline words,
   per-line vocab bullets, per-dialogue aggregate bullets, Finish Review.
4. **Vocab dashboard** — browse/filter/sort the vocab store by status,
   frequency, recency; promote `learning` → `learned`; manual
   add/edit/delete; a simple over-time chart of known+learned growth.
5. **Dialogue library** — list of imported dialogues, source, date,
   review status (draft vs. finished).

## 8. Future — Anki integration (spec only, not built in v1)

- A "study set" builder pulls from `learning`-status words, prioritized by
  frequency/recency/staleness.
- Example sentences for cards come first from real `occurrences[]` already
  captured on the `VocabEntry` (actual lines from dialogues you've
  studied) — these are more useful than generic sentences since you've
  already heard them in context.
- Where a word has too few/too-repetitive occurrences, generate additional
  example sentences via LLM, constrained to reuse only `known`/`learned`
  vocabulary so the sentence stays comprehensible (avoids testing three
  unknown words in one card).
- Export path: **AnkiConnect** (if Anki desktop is running locally) for
  direct push into a deck; fallback to `.apkg` generation (`genanki`) or
  CSV import when AnkiConnect isn't available.
- Card model (draft): front = jyutping sentence with target word
  blanked/highlighted; back = target word + hanzi + definition + English
  translation + source dialogue reference.
- One-directional export only — no read-back of Anki review history/SRS
  state into this app in the initial version.

## 9. Suggested stack

- **Backend**: Python + FastAPI — `pdfplumber` for PDF table extraction,
  `pycantonese` for hanzi segmentation, an in-memory dict loaded from the
  preprocessed CC-Canto `dictionary.json` (§6), Anthropic API for LLM
  fallback lookups/segmentation and segmentation validation.
  Python is the natural choice here mainly because the Cantonese NLP
  tooling (`pycantonese`) and PDF table extraction (`pdfplumber`) are both
  stronger in Python than their JS equivalents.
- **Frontend**: React (Vite) SPA talking to the local FastAPI server over
  `localhost`. Single user, no auth needed.
- Runs entirely locally: `uvicorn` backend + `vite` dev server, data lives
  under `data/` in the project.

**LLM auth for v1: your claude.ai login, not a metered API key.** Run
`ant auth login` once (the Anthropic CLI) to store an OAuth profile
locally; the Python SDK's default `anthropic.Anthropic()` client picks it
up automatically with no code change, and calls draw against your Pro/Max
subscription's usage rather than pay-per-token billing. Actual usage here
is cents to low dollars a year even calling the LLM for everything (see
cost discussion), so the binding constraint if any is Claude Code's shared
weekly/session rate limit, not money.

**Switching to metered API billing later is a zero-code-change:** the
SDK's credential resolution checks `ANTHROPIC_API_KEY` before the OAuth
profile — create a key at console.anthropic.com, set the env var, and
every call in the codebase starts billing through the API instead, with
nothing to rewrite.

## 10. Open questions for review

- How strict should "click to merge/split" segmentation editing be —
  freeform drag-select, or constrained to syllable boundaries only?
- For a word with multiple dictionary senses/homographs, v1 just takes the
  first sense rather than disambiguating — worth an LLM disambiguation
  pass using line context if this turns out to produce wrong glosses often
  enough to matter.
