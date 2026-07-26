"""Type 1 importer: structured table-format PDF (e.g. "Cantonese
Conversations" by Olly Richards). Each speaker turn is a 3-row table:
speaker+hanzi, jyutping, English.

Phase 5 research findings, not assumed in advance:

- `pdfplumber`'s `extract_tables()` resets at page boundaries, and a
  speaker turn that spans a page break gets split into TWO table
  fragments — one with a partial cell (continuation rows carry an
  empty-string speaker `''`, not the 3-rows-per-turn pattern the naive
  version assumed). Row content is therefore reconstructed by
  *classifying* each row's script (hanzi / jyutping / English) rather
  than trusting position alone, and a new turn starts only on a
  hanzi-classified row with a genuinely non-empty speaker cell.
- This PDF's embedded font encodes *some* hanzi (e.g. 行, 山 — but not
  most others) using their Kangxi Radical codepoints (U+2F00-U+2FDF)
  instead of standard CJK Unified Ideographs — invisible when printed
  (they render identically) but invisible to a CJK Unicode-range check
  too, and a mismatch against every downstream dictionary/segmentation
  lookup, which is keyed on the standard codepoint. Fixed by running
  `unicodedata.normalize("NFKC", ...)` on every cell at extraction time —
  NFKC's compatibility decomposition maps Kangxi Radicals back to their
  standard ideograph.

Both were caught by running this against the real 8-page sample, not a
synthetic one.
"""

import logging
import unicodedata
from dataclasses import dataclass, field
from datetime import date

import pdfplumber

from app.models.dialogue import StoredDialogue, StoredLine, StoredWordToken
from app.services import llm
from app.services.segmentation import (
    JYUTPING_SYLLABLE_PATTERN,
    compute_word_id,
    is_cjk_char,
    is_suspicious_merge,
    project_hanzi_to_jyutping,
)

logger = logging.getLogger(__name__)


@dataclass
class RawTurn:
    speaker: str
    hanzi: str
    jyutping: str
    english: str


def _classify_row(text: str) -> str:
    if any(is_cjk_char(ch) for ch in text):
        return "hanzi"
    tokens = text.split()
    if not tokens:
        return "english"
    jyutping_like = sum(1 for t in tokens if JYUTPING_SYLLABLE_PATTERN.search(t))
    return "jyutping" if jyutping_like / len(tokens) > 0.5 else "english"


def extract_raw_rows(pdf_path: str) -> list[list[str | None]]:
    """Flattens every table row across every page, in document order.

    Dialogue rows are always exactly 2 columns ([speaker_or_None, text]).
    The appendix "Vocabulary List" (SPEC.md §3 — a curated seed, not
    authoritative, and structurally a 3-column table: word | jyutping |
    definition) is excluded here on that column-count difference, not by
    page number — confirmed against the real sample rather than assumed.
    Capturing the appendix separately as a bonus definition seed is a
    clean future enhancement, not needed for a working Type 1 import.
    """
    rows: list[list[str | None]] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                rows.extend(row for row in table if len(row) == 2)
    return rows


def reconstruct_turns(rows: list[list[str | None]]) -> list[RawTurn]:
    """Merges the flattened row stream into speaker turns, stitching
    page-break-split cells back together by classified content type
    rather than trusting each table's row boundaries."""
    turns: list[RawTurn] = []
    current: RawTurn | None = None

    for row in rows:
        speaker_cell = row[0] if len(row) > 0 else None
        if speaker_cell:
            speaker_cell = unicodedata.normalize("NFKC", speaker_cell).strip()
        text_cell = row[1] if len(row) > 1 else None
        text = unicodedata.normalize("NFKC", (text_cell or "").replace("\n", " ")).strip()
        if not text:
            continue

        row_type = _classify_row(text)
        starts_new_turn = bool(speaker_cell) and row_type == "hanzi"

        if starts_new_turn:
            if current is not None:
                turns.append(current)
            current = RawTurn(speaker=speaker_cell, hanzi=text, jyutping="", english="")
            continue

        if current is None:
            continue  # stray row before any turn started (title/header rows etc.)

        if row_type == "hanzi":
            current.hanzi = f"{current.hanzi} {text}".strip()
        elif row_type == "jyutping":
            current.jyutping = f"{current.jyutping} {text}".strip()
        else:
            current.english = f"{current.english} {text}".strip()

    if current is not None:
        turns.append(current)

    return turns


@dataclass
class ImportResult:
    dialogue: StoredDialogue
    # Lines needing the LLM validation pass (SPEC.md §4 Step 2): failed to
    # align (Latin-script content or a genuine syllable count mismatch,
    # reason = "latin_script" / "syllable_count_mismatch"), or aligned
    # fine but pycantonese's segmentation is suspect (reason =
    # "suspicious_merge" — see segmentation.is_suspicious_merge). Each
    # becomes a single unsegmented-line token rather than being dropped,
    # so the dialogue stays complete while this list awaits reconciliation
    # (see reconcile_flagged_lines / llm.py).
    flagged_lines: list[dict] = field(default_factory=list)


def build_stored_dialogue(dialogue_id: str, title: str, turns: list[RawTurn]) -> ImportResult:
    lines: list[StoredLine] = []
    flagged: list[dict] = []

    for i, turn in enumerate(turns):
        line_id = f"line-{i}"
        result = project_hanzi_to_jyutping(turn.hanzi, turn.jyutping)
        merge_suspected = result.aligned and any(
            is_suspicious_merge(word.hanzi) for word in result.words
        )

        if result.aligned and not merge_suspected:
            tokens = [
                StoredWordToken(
                    token_id=f"{line_id}-w{j}",
                    word_id=compute_word_id(word.jyutping, word.hanzi),
                    jyutping=word.jyutping,
                    hanzi=word.hanzi,
                    trailing_punctuation=word.trailing_punctuation,
                )
                for j, word in enumerate(result.words)
            ]
        else:
            flagged.append(
                {
                    "line_id": line_id,
                    "speaker": turn.speaker,
                    "hanzi": turn.hanzi,
                    "jyutping": turn.jyutping,
                    "reason": result.reason if not result.aligned else "suspicious_merge",
                }
            )
            tokens = [
                StoredWordToken(
                    token_id=f"{line_id}-w0",
                    word_id=compute_word_id(turn.jyutping, turn.hanzi) or f"unresolved-{line_id}",
                    jyutping=turn.jyutping,
                    hanzi=turn.hanzi,
                )
            ]

        lines.append(StoredLine(id=line_id, speaker=turn.speaker, words=tokens, english=turn.english or None))

    dialogue = StoredDialogue(
        id=dialogue_id,
        title=title,
        lines=lines,
        source_type="structured_pdf",
        imported_at=date.today().isoformat(),
    )
    return ImportResult(dialogue=dialogue, flagged_lines=flagged)


def reconcile_flagged_lines(result: ImportResult) -> None:
    """Step 2's LLM pass: replaces each flagged line's single unsegmented
    placeholder token with a real per-word segmentation, mutating
    result.dialogue's lines in place. Best-effort — on any LLM failure the
    placeholder tokens are left as-is rather than failing the import,
    matching definitions.resolve_definition()'s graceful-degradation
    pattern (validate_segmentation_batch itself already logs a per-chunk
    warning on failure; this only needs to log the lines that still came
    back with nothing, so an unresolved-word bug report can be traced
    back to *why* without re-running the import)."""
    if not result.flagged_lines:
        return

    try:
        segmented = llm.validate_segmentation_batch(result.flagged_lines)
    except Exception:
        logger.warning("reconcile_flagged_lines: validate_segmentation_batch call failed", exc_info=True)
        return

    unresolved = [f["line_id"] for f in result.flagged_lines if not segmented.get(f["line_id"])]
    if unresolved:
        logger.warning("reconcile_flagged_lines: no segmentation returned for line_ids=%s", unresolved)

    lines_by_id = {line.id: line for line in result.dialogue.lines}
    for line_id, words in segmented.items():
        line = lines_by_id.get(line_id)
        if line is None or not words:
            continue
        line.words = [
            StoredWordToken(
                token_id=f"{line_id}-w{j}",
                word_id=compute_word_id(jyutping, hanzi) or f"unresolved-{line_id}-w{j}",
                jyutping=jyutping,
                hanzi=hanzi,
                trailing_punctuation=trailing_punctuation,
            )
            for j, (hanzi, jyutping, trailing_punctuation) in enumerate(words)
        ]


def parse_structured_pdf(pdf_path: str) -> list[RawTurn]:
    rows = extract_raw_rows(pdf_path)
    return reconstruct_turns(rows)


def import_structured_pdf(pdf_path: str, dialogue_id: str, title: str) -> ImportResult:
    turns = parse_structured_pdf(pdf_path)
    result = build_stored_dialogue(dialogue_id, title, turns)
    reconcile_flagged_lines(result)
    return result
