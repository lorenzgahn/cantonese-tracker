"""LLM call sites. Auth is via the user's claude.ai OAuth login
(`ant auth login`) per SPEC.md §9 — anthropic.Anthropic() picks up the
OAuth profile automatically with no code change; ANTHROPIC_API_KEY (if
ever set) is checked first by the SDK, so switching to metered billing
later needs no changes here either. Confirmed live (Phase 0.5): auth
succeeds, and the account needs API credits purchased separately at
console.anthropic.com — a claude.ai Pro/Max subscription does not cover
raw API calls, even authenticated via the same OAuth login.

define_word() is Step 3's per-word, on-click fallback (lazy — only ever
called for a word that's actually been flagged unknown).
generate_jyutping_batch() (Step 1a) and validate_segmentation_batch()
(Step 2) are the per-dialogue *batched* passes named in SPEC.md §4 —
one call per dialogue's flagged items, not one call per item, matching
the cost-efficiency design discussed for this app. Both use
client.messages.parse() with a Pydantic schema rather than free-text
parsing, since the result has to programmatically re-slot back into
specific words/lines by hanzi or line_id — a schema guarantees that
shape rather than hoping the model's prose matches a regex.
"""

import logging
import re

import anthropic
from pydantic import BaseModel

from app.config import ANTHROPIC_MODEL

logger = logging.getLogger(__name__)

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def define_word(
    *, jyutping: str, hanzi: str | None, line_context: str, english_context: str | None = None
) -> str:
    """Short, plain-English, learner-oriented gloss for a word the
    dictionary didn't have — matching the style the user already gets
    pasting into ChatGPT by hand (see SPEC.md §1). english_context, when
    available (PDF imports with a translation row), is the single
    biggest lever for matching that ChatGPT-pasted quality — it's the
    same grounding a human would implicitly have from reading the whole
    exchange, and this word has none from the dictionary since it wasn't
    found there at all."""
    client = _get_client()
    word_desc = f'"{jyutping}"' + (f" ({hanzi})" if hanzi else "")
    context_desc = f"In the sentence:\n{line_context}"
    if english_context:
        context_desc += f'\n\nThat sentence translates to: "{english_context}"'
    prompt = (
        "You are helping a Cantonese learner. "
        f"{context_desc}\n\n"
        f"Give a short, plain-English definition (5-10 words) for the word "
        f"{word_desc}. Reply with ONLY the definition text — no preamble, "
        "no quotes, no restating the word."
    )
    response = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    text = next((b.text for b in response.content if b.type == "text"), "").strip()
    if not text:
        raise RuntimeError(f"LLM returned no text (stop_reason={response.stop_reason!r})")
    return text


def pick_definition_sense(
    *,
    jyutping: str,
    hanzi: str | None,
    candidates: list[str],
    line_context: str,
    english_context: str | None = None,
) -> str:
    """The dictionary has this word, but with more than one listed sense
    (see definitions.py's candidate-flattening) — picks (or lightly
    rephrases) whichever one actually fits this occurrence, grounded in
    the real dictionary senses rather than inventing a new one from
    scratch. english_context, when available, is the strongest signal
    this gets; line_context (bare jyutping) is always given as a
    fallback. Reused for both a true multi-sense CC-Canto entry and
    genuine duplicate entries across CC-Canto/CC-CEDICT that happen to
    list different definitions for the same hanzi+jyutping."""
    client = _get_client()
    word_desc = f'"{jyutping}"' + (f" ({hanzi})" if hanzi else "")
    candidates_desc = "\n".join(f"{i + 1}. {c}" for i, c in enumerate(candidates))
    context_desc = f"Here is the sentence it appears in:\n{line_context}"
    if english_context:
        context_desc += f'\n\nThat sentence translates to: "{english_context}"'
    prompt = (
        f"You are helping a Cantonese learner. The word {word_desc} has more than one "
        f"possible dictionary sense:\n{candidates_desc}\n\n"
        f"{context_desc}\n\n"
        "Pick whichever sense actually fits this specific use. Reply with ONLY that "
        "definition's text — you may lightly rephrase it for clarity, but stay faithful "
        "to one of the listed senses; do not invent a new one. No preamble, no numbering, "
        "no quotes."
    )
    response = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    text = next((b.text for b in response.content if b.type == "text"), "").strip()
    if not text:
        raise RuntimeError(f"LLM returned no text (stop_reason={response.stop_reason!r})")
    return text


class _GeneratedWord(BaseModel):
    hanzi: str
    jyutping: str


class _GeneratedWordBatch(BaseModel):
    words: list[_GeneratedWord]


def generate_jyutping_batch(hanzi_words: list[str]) -> dict[str, str]:
    """Step 1a's LLM fallback: jyutping for hanzi words the dictionary
    (whole-word and per-character) couldn't resolve at all — one call for
    every such word in a dialogue, not one call per word. Returns a
    hanzi -> jyutping map; words the model couldn't produce are simply
    absent from the result, so callers can tell a real miss from success."""
    if not hanzi_words:
        return {}
    client = _get_client()
    word_list = "\n".join(f"- {w}" for w in hanzi_words)
    prompt = (
        "You are helping build a Cantonese learning tool. For each of the "
        "following Cantonese (hanzi) words, give its Jyutping romanization "
        "(with tone numbers, no spaces within a word). These words were not "
        f"found in a dictionary lookup, so use your own knowledge:\n\n{word_list}"
    )
    response = client.messages.parse(
        model=ANTHROPIC_MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
        output_format=_GeneratedWordBatch,
    )
    return {w.hanzi: w.jyutping for w in response.parsed_output.words}


class _SegmentedWord(BaseModel):
    hanzi: str
    jyutping: str
    # Punctuation immediately after this word in the source line (".",
    # "...", "?", ...) — empty string if none. Kept separate from
    # `jyutping` deliberately: PDF imports display it but must not fold
    # it into word identity (see project_hanzi_to_jyutping's equivalent
    # non-LLM path and jyutping_utils.compute_word_id for why).
    trailing_punctuation: str = ""


class _SegmentedLine(BaseModel):
    line_id: str
    words: list[_SegmentedWord]


class _SegmentationBatch(BaseModel):
    lines: list[_SegmentedLine]


# --- Long-line pre-splitting + size-based batching ---
#
# Flagged lines can be whole speaker turns (a PDF turn stays one unit
# until reconciled), and some turns are full monologues, not sentences —
# confirmed live on a real transcript ("17 Snow's Year in the
# Netherlands") with turns up to 1,084 jyutping / 286 hanzi characters. A
# single line that long can overrun one LLM call's output budget on its
# own, regardless of how many *other* lines it's batched with — an
# earlier fix that only chunked by a fixed *count* of flagged lines
# wasn't enough (that dialogue still had 7 lines unresolved afterward).
# So flagged lines now go through two stages before any LLM call:
#   1. Any line longer than _LONG_LINE_SPLIT_THRESHOLD is pre-split at
#      matching punctuation boundaries in *both* hanzi and jyutping (see
#      _split_flagged_line) into several smaller pieces, tagged with a
#      synthetic line_id sharing the original as a prefix.
#   2. All pieces (split or not) are packed into LLM calls by a running
#      character budget (_pack_into_chunks), not a fixed item count, so
#      a batch of short lines packs efficiently while long pieces
#      automatically get fewer neighbors per call.
# Results are reassembled back under the *original* line_id afterward
# (_reassemble_results), so callers (pdf_parser.py, hanzi_narrative.py)
# see the exact same dict[str, list[tuple]] shape as before — none of
# this is visible outside this module.

_LONG_LINE_SPLIT_THRESHOLD = 80  # hanzi chars — longer than this gets pre-split
_CHUNK_CHAR_BUDGET = 200  # total hanzi chars packed into one LLM call

_STRONG_SENTENCE_BOUNDARY = re.compile(r"(?:\.\.\.|[.?!…。？！])+")
_CLAUSE_BOUNDARY = re.compile(r"(?:,|，|、|;|；)+")


def _split_at(text: str, pattern: re.Pattern) -> list[str]:
    """Splits text right after each match of `pattern`, keeping the
    matched punctuation attached to the end of the preceding piece. A
    lossless partition — concatenating the returned pieces reproduces
    `text` exactly."""
    pieces = []
    cursor = 0
    for m in pattern.finditer(text):
        pieces.append(text[cursor : m.end()])
        cursor = m.end()
    if cursor < len(text):
        pieces.append(text[cursor:])
    return pieces


def _split_flagged_line(hanzi: str, jyutping: str, max_len: int) -> list[tuple[str, str]]:
    """Splits one flagged line's (hanzi, jyutping) into aligned pieces at
    matching punctuation boundaries — sentence-ending first (. ? ! ...
    … 。？！), falling back to clause punctuation (, ， 、 ; ；) for any
    resulting sentence still over max_len. jyutping may be empty (Type
    4's synthesized lines have no hint); then only hanzi's boundaries
    are used. Falls back to *not* splitting a piece — hanzi and jyutping
    stay together whole, still over budget — at any point the two sides
    don't produce a matching number of pieces, since a wrong pairing
    would silently misalign the reconciliation rather than just being
    slow."""
    if len(hanzi) <= max_len:
        return [(hanzi, jyutping)]

    # Not short-circuited when this comes back as a single "sentence"
    # (no strong-boundary match, or only one right at the very end) —
    # the per-sentence loop below still tries the weaker clause-boundary
    # pass on it, which is exactly what a long comma-heavy run-on with
    # no sentence-ending punctuation until the end needs.
    hanzi_sentences = _split_at(hanzi, _STRONG_SENTENCE_BOUNDARY)

    if jyutping:
        jyutping_sentences = _split_at(jyutping, _STRONG_SENTENCE_BOUNDARY)
        if len(jyutping_sentences) != len(hanzi_sentences):
            return [(hanzi, jyutping)]
    else:
        jyutping_sentences = [""] * len(hanzi_sentences)

    pairs: list[tuple[str, str]] = []
    for h_sent, j_sent in zip(hanzi_sentences, jyutping_sentences):
        if len(h_sent) <= max_len:
            pairs.append((h_sent, j_sent))
            continue
        h_clauses = _split_at(h_sent, _CLAUSE_BOUNDARY)
        if j_sent:
            j_clauses = _split_at(j_sent, _CLAUSE_BOUNDARY)
            if len(j_clauses) != len(h_clauses):
                pairs.append((h_sent, j_sent))
                continue
        else:
            j_clauses = [""] * len(h_clauses)
        if len(h_clauses) <= 1:
            pairs.append((h_sent, j_sent))
        else:
            pairs.extend(zip(h_clauses, j_clauses))

    return _regroup_pairs(pairs, max_len)


def _regroup_pairs(pairs: list[tuple[str, str]], max_len: int) -> list[tuple[str, str]]:
    """Rejoins adjacent small (hanzi, jyutping) pieces up to max_len, so
    splitting doesn't send one LLM item per single short sentence when
    several would comfortably fit in one."""
    grouped: list[tuple[str, str]] = []
    cur_h, cur_j, cur_len = "", "", 0
    for h, j in pairs:
        if cur_h and cur_len + len(h) > max_len:
            grouped.append((cur_h, cur_j))
            cur_h, cur_j, cur_len = "", "", 0
        cur_h += h
        cur_j += j
        cur_len += len(h)
    if cur_h:
        grouped.append((cur_h, cur_j))
    return grouped


def _prepare_segmentation_items(flagged_lines: list[dict]) -> list[dict]:
    """Expands each flagged line into one or more LLM-call items, pre-
    splitting anything over _LONG_LINE_SPLIT_THRESHOLD (see
    _split_flagged_line). Every item carries "_parent_line_id" pointing
    back to the original flagged line's line_id, used by
    _reassemble_results to stitch split pieces back together; an item
    from a line that wasn't split has "_parent_line_id" == its own
    line_id."""
    items: list[dict] = []
    for item in flagged_lines:
        pieces = _split_flagged_line(item["hanzi"], item.get("jyutping", ""), _LONG_LINE_SPLIT_THRESHOLD)
        if len(pieces) == 1:
            hanzi, jyutping = pieces[0]
            items.append({**item, "hanzi": hanzi, "jyutping": jyutping, "_parent_line_id": item["line_id"]})
            continue
        for i, (hanzi, jyutping) in enumerate(pieces):
            items.append(
                {
                    "line_id": f"{item['line_id']}__part{i}",
                    "hanzi": hanzi,
                    "jyutping": jyutping,
                    "_parent_line_id": item["line_id"],
                }
            )
    return items


def _pack_into_chunks(items: list[dict], max_chars: int) -> list[list[dict]]:
    """Groups items into LLM-call batches by a running hanzi-character
    budget rather than a fixed item count, so a call with several short
    lines can pack many in while a call touching a long (post-split)
    piece automatically gets fewer neighbors. A single item longer than
    max_chars still gets its own chunk rather than being dropped."""
    chunks: list[list[dict]] = []
    current: list[dict] = []
    current_len = 0
    for item in items:
        item_len = len(item["hanzi"])
        if current and current_len + item_len > max_chars:
            chunks.append(current)
            current = []
            current_len = 0
        current.append(item)
        current_len += item_len
    if current:
        chunks.append(current)
    return chunks


def _reassemble_results(
    prepared_items: list[dict], raw_results: dict[str, list[tuple[str, str, str]]]
) -> dict[str, list[tuple[str, str, str]]]:
    """Stitches per-item results back together under each item's
    original (pre-split) line_id, in the same order the pieces were
    produced in. A line whose pieces only partially succeeded still
    contributes whatever pieces did resolve, rather than discarding the
    whole line — validate_segmentation_batch logs that case separately
    from a full miss."""
    final: dict[str, list[tuple[str, str, str]]] = {}
    for item in prepared_items:
        words = raw_results.get(item["line_id"])
        if not words:
            continue
        final.setdefault(item["_parent_line_id"], []).extend(words)
    return final


def validate_segmentation_batch(flagged_lines: list[dict]) -> dict[str, list[tuple[str, str, str]]]:
    """Step 2's LLM fallback: word-level (hanzi, jyutping, trailing
    punctuation) segmentation for lines the automatic aligner/segmenter
    couldn't handle (code-switched Latin-script spans, syllable-count
    mismatches, trie misses). Each item in flagged_lines needs "line_id",
    "hanzi", and "jyutping" (the line's original, unsegmented jyutping,
    used as a hint — may be empty for Type 4's synthesized case). Long
    lines are pre-split at punctuation boundaries and everything is then
    packed into LLM calls by a character budget (see the module comment
    above) before any call happens, then reassembled back under each
    line's original line_id. Returns line_id -> ordered
    [(hanzi, jyutping, trailing_punctuation), ...]; a line_id absent from
    the result means nothing came back for any of its pieces — logged
    either way (a full miss, or a partial one), not raised, matching this
    module's other batch calls' degrade-gracefully contract."""
    if not flagged_lines:
        return {}

    prepared = _prepare_segmentation_items(flagged_lines)
    chunks = _pack_into_chunks(prepared, _CHUNK_CHAR_BUDGET)

    raw_results: dict[str, list[tuple[str, str, str]]] = {}
    for chunk in chunks:
        try:
            raw_results.update(_validate_segmentation_chunk(chunk))
        except Exception:
            logger.warning(
                "validate_segmentation_batch: chunk failed for line_ids=%s",
                [item["line_id"] for item in chunk],
                exc_info=True,
            )

    result = _reassemble_results(prepared, raw_results)

    expected_parents = {item["_parent_line_id"] for item in prepared}
    missing = sorted(expected_parents - result.keys())
    if missing:
        logger.warning("validate_segmentation_batch: no segmentation for line_ids=%s", missing)

    partial = sorted(
        {
            item["_parent_line_id"]
            for item in prepared
            if item["_parent_line_id"] in result and item["line_id"] not in raw_results
        }
    )
    if partial:
        logger.warning(
            "validate_segmentation_batch: line_ids=%s only partially reconciled (some split parts failed)", partial
        )

    return result


def _validate_segmentation_chunk(flagged_lines: list[dict]) -> dict[str, list[tuple[str, str, str]]]:
    client = _get_client()
    lines_desc = "\n".join(
        f'- line_id="{item["line_id"]}": hanzi="{item["hanzi"]}"'
        + (f', jyutping hint="{item["jyutping"]}"' if item.get("jyutping") else "")
        for item in flagged_lines
    )
    prompt = (
        "You are helping build a Cantonese learning tool. For each line below, "
        "split the hanzi into individual words (the smallest units a learner "
        "would look up) and give the Jyutping romanization for each word "
        "(with tone numbers, no spaces within a word). Preserve word order.\n\n"
        "Split fixed colloquial phrases into their component words too — do "
        "not keep a multi-word phrase as one token just because it's "
        "commonly said together as a set expression. For example:\n"
        "  - 好耐冇見 (\"long time no see\") must be split into 好耐 / 冇 / 見, "
        "not kept as one word.\n"
        "  - 着件雨褸 (\"put on a raincoat\") must be split into 着 / 件 / 雨褸, "
        "not kept as one word.\n"
        "Only keep multiple characters as a single word when they form one "
        "indivisible lexical item on their own, independent of surrounding "
        "context — e.g. 星期日 (\"Sunday\"), 獅子山 (\"Lion Rock\", a proper "
        "noun). As a rule of thumb, a word longer than 3 characters should "
        "be rare; if you're not confident a run of characters is a single "
        "dictionary entry on its own, split it further.\n\n"
        "Do not drop punctuation. If a word is immediately followed by a "
        "punctuation mark in the source (a period, comma, ellipsis, question "
        "mark, etc.), put that punctuation in the word's trailing_punctuation "
        "field — do not include it in jyutping, and do not create a separate "
        "token for it. A word with nothing following it has an empty "
        "trailing_punctuation. Keep embedded English/Latin-script words as "
        "their own word entry, with the English word itself as its "
        "\"jyutping\" value. If a jyutping hint is given, use it to guide "
        "your romanization, but the hanzi word boundaries are what you need "
        "to determine:\n\n"
        f"{lines_desc}"
    )
    response = client.messages.parse(
        model=ANTHROPIC_MODEL,
        # 16000 comfortably covers one _CHUNK_CHAR_BUDGET-sized chunk (see
        # the module-level comment above _LONG_LINE_SPLIT_THRESHOLD for
        # why pre-splitting + character-budget packing exist at all).
        # Confirmed live that repeated calls on the same input can disagree
        # on whether to split a common fixed phrase (e.g. 好耐冇見) into its
        # component words or keep it as one token. temperature=0 would
        # normally help, but ANTHROPIC_MODEL (claude-opus-4-8) rejects it
        # ("temperature is deprecated for this model") — the explicit
        # splitting rule + worked examples in the prompt above is what's
        # actually carrying the fix here.
        max_tokens=16000,
        messages=[{"role": "user", "content": prompt}],
        output_format=_SegmentationBatch,
    )
    return {
        line.line_id: [(w.hanzi, w.jyutping, w.trailing_punctuation) for w in line.words]
        for line in response.parsed_output.lines
    }
