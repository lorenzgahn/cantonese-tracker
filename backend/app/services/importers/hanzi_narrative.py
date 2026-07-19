"""Type 4 importer: hanzi-only narrative text — no jyutping, no English,
no speaker structure. Numbered `[N]` scene markers delimit paragraphs of
narration (possibly with embedded `「...」` dialogue); each becomes one
Line with speaker=None. A marker can carry a letter suffix to subdivide
a numbered scene into its own chunks — `[1a]`, `[1b]`, `[2a]` are each
their own scene, distinct from `[1]`/`[2]` alone — confirmed against
real input, not hypothesized.

Step 1a (SPEC.md §4): jyutping doesn't exist yet, so it has to be
*generated* rather than aligned:

1. Whole-word dictionary lookup (CC-Canto, via app.services.dictionary)
   — highest confidence.
2. Per-character fallback, concatenated — used when the whole word isn't
   a CC-Canto entry (common for ordinary vocabulary and names; CC-Canto
   skews toward curated idioms/slang, confirmed against the real sample:
   星期日 "Sunday", 文仔 the character's name, and 媽媽 "mom" are all
   whole-word misses, but resolve fine per-character). Flagged as lower
   confidence — concatenating single-character readings doesn't always
   reflect the compound's actual pronunciation.
3. Still unresolved (a character with no dictionary entry at all — e.g.
   期 in 星期日 turned out to be missing even standalone) — flagged for
   the LLM pass, word-level (not line-level like Type 1: there's no
   existing jyutping to align against here, so a per-word miss doesn't
   invalidate its neighbors the way a Type-1 alignment failure does).

Before any of the above: pycantonese.segment() itself can produce a bad
word boundary, not just a jyutping gap — confirmed against the real
sample text, where unfamiliar vocabulary (雨褸 "raincoat") got glued to
an adjacent unrelated word (新雨褸 = 新 "new" + 雨褸, 同青蛙 = 同 "with"
+ 青蛙 "frog"). Since there's no existing jyutping to sanity-check word
lengths against here (unlike Type 1's syllable-count check), this is
caught with a dictionary-based heuristic instead
(segmentation.is_suspicious_merge) and the whole scene is set aside for
LLM re-segmentation rather than trusting the bad split.

This importer is the first one where the LLM pass is genuinely
load-bearing rather than an edge-case fallback — real coverage gaps
appear on ordinary narrative vocabulary, confirmed against the real
sample text, not hypothesized.
"""

import re
from dataclasses import dataclass, field
from datetime import date

from app.models.dialogue import StoredDialogue, StoredLine, StoredWordToken
from app.services import dictionary, llm
from app.services.segmentation import compute_word_id, is_suspicious_merge, segment_hanzi

_SCENE_MARKER_PATTERN = re.compile(r"\[(\d+[a-z]*)\]")


@dataclass
class GeneratedWord:
    hanzi: str
    jyutping: str
    confidence: str  # "dictionary" | "per_character" | "unresolved"


@dataclass
class ImportResult:
    dialogue: StoredDialogue
    # Word-level, each {"line_id", "hanzi", "reason"} — "reason" is
    # "per_character_fallback_used" (usable now, worth reconciling later)
    # or "no_dictionary_match" (no jyutping at all, needs the LLM pass).
    flagged_words: list[dict] = field(default_factory=list)
    # Scene-level, each {"line_id", "hanzi", "reason": "suspicious_merge"} —
    # pycantonese.segment() produced a word boundary that's probably wrong
    # (see segmentation.is_suspicious_merge), so the whole scene is set
    # aside for LLM re-segmentation rather than trusting per-word jyutping
    # generation on a bad split.
    flagged_lines: list[dict] = field(default_factory=list)


def split_scenes(text: str) -> list[tuple[str, str]]:
    """Splits on `[N]` / `[Na]` markers, returning (marker, block_text)
    pairs in order. Content before the first marker (if any) is
    discarded."""
    parts = _SCENE_MARKER_PATTERN.split(text)
    scenes: list[tuple[str, str]] = []
    for i in range(1, len(parts), 2):
        marker = parts[i]
        block = parts[i + 1].strip() if i + 1 < len(parts) else ""
        if block:
            scenes.append((marker, block))
    return scenes


def generate_word_jyutping(hanzi_word: str) -> GeneratedWord:
    hits = dictionary.lookup(hanzi=hanzi_word)
    if hits:
        return GeneratedWord(hanzi=hanzi_word, jyutping=hits[0]["jyutping"], confidence="dictionary")

    per_char_readings = []
    for ch in hanzi_word:
        ch_hits = dictionary.lookup(hanzi=ch)
        if not ch_hits:
            return GeneratedWord(hanzi=hanzi_word, jyutping="", confidence="unresolved")
        per_char_readings.append(ch_hits[0]["jyutping"])
    return GeneratedWord(
        hanzi=hanzi_word, jyutping=" ".join(per_char_readings), confidence="per_character"
    )


def build_stored_dialogue(dialogue_id: str, title: str, raw_text: str) -> ImportResult:
    scenes = split_scenes(raw_text)
    lines: list[StoredLine] = []
    flagged_words: list[dict] = []
    flagged_lines: list[dict] = []

    for marker, block in scenes:
        line_id = f"scene-{marker}"
        words = [word for word, _span in segment_hanzi(block)]

        if any(is_suspicious_merge(word) for word in words):
            flagged_lines.append({"line_id": line_id, "hanzi": block, "reason": "suspicious_merge"})
            tokens = [
                StoredWordToken(
                    token_id=f"{line_id}-w0",
                    word_id=f"unresolved-{line_id}",
                    jyutping=f"[{block}]",
                    hanzi=block,
                )
            ]
            lines.append(StoredLine(id=line_id, speaker=None, words=tokens))
            continue

        tokens = []
        for j, word in enumerate(words):
            generated = generate_word_jyutping(word)

            if generated.confidence == "unresolved":
                flagged_words.append(
                    {"line_id": line_id, "hanzi": word, "reason": "no_dictionary_match"}
                )
                jyutping = f"[{word}]"  # visually distinct placeholder, not a guessed reading
            else:
                jyutping = generated.jyutping
                if generated.confidence == "per_character":
                    flagged_words.append(
                        {"line_id": line_id, "hanzi": word, "reason": "per_character_fallback_used"}
                    )

            word_id = compute_word_id(jyutping, word) or f"unresolved-{line_id}-w{j}"
            tokens.append(
                StoredWordToken(token_id=f"{line_id}-w{j}", word_id=word_id, jyutping=jyutping, hanzi=word)
            )

        lines.append(StoredLine(id=line_id, speaker=None, words=tokens))

    dialogue = StoredDialogue(
        id=dialogue_id,
        title=title,
        lines=lines,
        source_type="hanzi_narrative",
        imported_at=date.today().isoformat(),
    )
    return ImportResult(dialogue=dialogue, flagged_words=flagged_words, flagged_lines=flagged_lines)


def reconcile_unresolved_words(result: ImportResult) -> None:
    """Step 1a's LLM pass: fills in real jyutping for words build_stored_dialogue
    left as `[bracketed]` placeholders (reason == "no_dictionary_match"),
    mutating result.dialogue's tokens in place. Best-effort — on any LLM
    failure the placeholders are left as-is rather than failing the import,
    matching definitions.resolve_definition()'s graceful-degradation pattern."""
    unresolved_hanzi = {
        f["hanzi"] for f in result.flagged_words if f["reason"] == "no_dictionary_match"
    }
    if not unresolved_hanzi:
        return

    try:
        generated = llm.generate_jyutping_batch(sorted(unresolved_hanzi))
    except Exception:
        return

    if not generated:
        return

    for line in result.dialogue.lines:
        for token in line.words:
            new_jyutping = generated.get(token.hanzi)
            if new_jyutping and token.jyutping == f"[{token.hanzi}]":
                token.jyutping = new_jyutping
                token.word_id = compute_word_id(new_jyutping, token.hanzi) or token.word_id


def reconcile_flagged_lines(result: ImportResult) -> None:
    """Re-segments scenes build_stored_dialogue set aside as a suspected
    pycantonese merge, replacing each one's single placeholder token with
    the LLM's word-level split. Reuses validate_segmentation_batch (built
    for Type 1's PDF importer) rather than a separate function — the task
    is identical, just with no jyutping hint to guide it here since none
    exists for this input type. Best-effort — on any LLM failure the
    placeholder is left as-is rather than failing the import, matching
    definitions.resolve_definition()'s graceful-degradation pattern."""
    if not result.flagged_lines:
        return

    try:
        segmented = llm.validate_segmentation_batch(
            [{"line_id": f["line_id"], "hanzi": f["hanzi"]} for f in result.flagged_lines]
        )
    except Exception:
        return

    if not segmented:
        return

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
            )
            for j, (hanzi, jyutping) in enumerate(words)
        ]


def import_hanzi_narrative(raw_text: str, dialogue_id: str, title: str) -> ImportResult:
    result = build_stored_dialogue(dialogue_id, title, raw_text)
    reconcile_unresolved_words(result)
    reconcile_flagged_lines(result)
    return result
