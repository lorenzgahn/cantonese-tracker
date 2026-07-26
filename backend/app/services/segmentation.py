"""Step 2 segmentation core.

Verified against the installed pycantonese==5.0.0 (Phase 4 research —
its actual API differs from what SPEC.md assumed, corrected here):

- `pycantonese.segment(text, offsets=True)` returns `(word, (start, end))`
  tuples with exact character offsets — no need to hand-compute
  cumulative offsets from word lengths, as originally planned.
- There is no `Segmenter(allow=..., disallow=...)` customization class in
  this version; tuning around a bad split (if one is ever observed) will
  need a different approach when it comes up.
- pycantonese ships a `CHARS_TO_JYUTPING` single-character lookup table,
  but it is NOT used here: verified it gives the *wrong* reading for
  common polyphonic characters in context — e.g. it maps 行 to `hong6`
  (row/business), but 行山 ("to hike") needs `haang4`. Whole-word
  dictionary lookup (CC-Canto, via app.services.dictionary) is the
  trusted source for word-level jyutping instead.
"""

import re
from dataclasses import dataclass, field

import pycantonese

from app.services import dictionary
from app.services.jyutping_utils import compute_word_id, normalize_jyutping_key  # noqa: F401 (re-exported)

JYUTPING_SYLLABLE_PATTERN = re.compile(r"[a-zA-Z]+[0-9]")
_LATIN_SCRIPT_PATTERN = re.compile(r"[a-zA-Z]")


def has_latin_script(text: str) -> bool:
    return bool(_LATIN_SCRIPT_PATTERN.search(text))

# Matches pycantonese.segment's own default ceiling on word length.
_MAX_JYUTPING_TRIE_WORD_LENGTH = 5

_CJK_RUN_PATTERN = re.compile(r"[一-鿿㐀-䶿]+")


def segment_hanzi(text: str) -> list[tuple[str, tuple[int, int]]]:
    """Wraps pycantonese.segment(), then splits each returned token into
    maximal CJK-only runs.

    Needed because pycantonese can return a token with punctuation
    embedded *inside* it, not just adjacent — found on real narrative
    text with an unknown proper noun nearby: segmenting "...好靚，文仔好
    想..." returned '靚，文仔' as a single token, comma included, in the
    middle. project_hanzi_to_jyutping's per-token `_cjk_only` strips
    non-CJK characters but doesn't re-split on them, so a token like that
    would silently glue two unrelated words together (靚 + 文仔) instead
    of being treated as two words with a punctuation boundary between
    them. Splitting here, once, fixes it for every caller.

    The returned offsets are sequential over the *emitted* CJK runs, not
    true positions in the original string (dropped punctuation isn't
    represented) — fine for both current callers, which only use them for
    ordering/length, never to index back into the source text.
    """
    raw_words = pycantonese.segment(text)
    result: list[tuple[str, tuple[int, int]]] = []
    cursor = 0
    for word in raw_words:
        for run in _CJK_RUN_PATTERN.findall(word):
            result.append((run, (cursor, cursor + len(run))))
            cursor += len(run)
    return result


# Real Cantonese words this long are almost always either a whole-word
# CC-Canto entry (idioms/proper compounds) or a dictionary gap on an
# otherwise-correct word (e.g. 星期日) — either way a whole-word lookup
# passes them through untouched. A 3+ char run that ALSO misses the
# dictionary is much more often pycantonese gluing two unrelated words
# together on unfamiliar vocabulary — confirmed against a real sample
# ("同青蛙" = 同 "with" + 青蛙 "frog"; "新雨褸" = 新 "new" + 雨褸
# "raincoat"; up to 4 chars stacked, e.g. "件雨褸橙").
_MIN_SUSPICIOUS_MERGE_LENGTH = 3


def is_suspicious_merge(hanzi: str) -> bool:
    return len(hanzi) >= _MIN_SUSPICIOUS_MERGE_LENGTH and not dictionary.lookup(hanzi=hanzi)


def is_cjk_char(ch: str) -> bool:
    # CJK Unified Ideographs (U+4E00-U+9FFF) *and* Extension A
    # (U+3400-U+4DBF). Extension A matters here: Cantonese-specific
    # particles like 㗎 (U+35CE) live there, not in the main block — a
    # range check on the main block alone silently drops them (found via
    # a real sample line, not a hypothetical).
    return "一" <= ch <= "鿿" or "㐀" <= ch <= "䶿"


@dataclass
class WordSpan:
    hanzi: str
    jyutping: str  # space-joined syllables for this word
    # Punctuation immediately following this word in the source line
    # (".", "...", "?", ...), kept out of `jyutping` deliberately — display
    # only, on WordToken.trailing_punctuation. Folding it into `jyutping`
    # would fold it into word_id too (see jyutping_utils.compute_word_id),
    # so the same word would fragment into a different vocab entry
    # depending on whether it happened to sit at a clause boundary.
    trailing_punctuation: str = ""


@dataclass
class ProjectionResult:
    words: list[WordSpan] = field(default_factory=list)
    aligned: bool = True
    # Set when aligned=False, so the caller's LLM batch (Phase 5/6) can
    # log/prompt differently for "there's code-switched English in here"
    # vs "the syllable count just didn't match up."
    reason: str | None = None


def project_hanzi_to_jyutping(hanzi_line: str, jyutping_line: str) -> ProjectionResult:
    """Type 1 path: jyutping already exists (extracted from a PDF row) —
    slice it into per-word spans using pycantonese's hanzi segmentation.

    Asserts the syllable count matches the (punctuation-stripped) hanzi
    character count; on mismatch, returns aligned=False rather than
    guessing at a misaligned slice — SPEC.md is explicit that a whole
    misaligned line should be flagged for the LLM pass, not silently
    sliced wrong. Punctuation between/after syllables in jyutping_line is
    recovered via each syllable match's real position (a plain .findall()
    would discard that) and attached to the preceding word as
    WordSpan.trailing_punctuation, so PDF imports keep it instead of
    silently dropping it.
    """
    # Checked explicitly and first: filtering both sides down to CJK-only
    # / tone-digit-only tokens means a code-switched word (no hanzi, no
    # tone digit) can silently vanish from *both* counts and the syllable
    # count still coincidentally matches — verified this actually happens
    # against a real sample line ("... instagram ...", "... po ..."). A
    # count match alone isn't enough; a Latin-script line always needs
    # the LLM pass, per SPEC.md §4 Step 2.
    if has_latin_script(hanzi_line):
        return ProjectionResult(words=[], aligned=False, reason="latin_script")

    # segment_hanzi already returns pure CJK-only runs (see its docstring)
    # — no further stripping/filtering needed here.
    hanzi_words = [word for word, _span in segment_hanzi(hanzi_line)]
    total_hanzi_chars = sum(len(word) for word in hanzi_words)

    syllable_matches = list(JYUTPING_SYLLABLE_PATTERN.finditer(jyutping_line))
    syllables = [m.group() for m in syllable_matches]

    if len(syllables) != total_hanzi_chars:
        return ProjectionResult(words=[], aligned=False, reason="syllable_count_mismatch")

    words: list[WordSpan] = []
    cursor = 0
    for word in hanzi_words:
        n = len(word)
        word_matches = syllable_matches[cursor : cursor + n]
        jyutping_text = " ".join(m.group() for m in word_matches)

        next_start = (
            syllable_matches[cursor + n].start() if cursor + n < len(syllable_matches) else len(jyutping_line)
        )
        trailing_punctuation = jyutping_line[word_matches[-1].end() : next_start].strip()

        words.append(WordSpan(hanzi=word, jyutping=jyutping_text, trailing_punctuation=trailing_punctuation))
        cursor += n
    return ProjectionResult(words=words, aligned=True)


def segment_jyutping_trie(
    jyutping_line: str, max_word_syllables: int = _MAX_JYUTPING_TRIE_WORD_LENGTH
) -> list[str]:
    """Type 2 path: no hanzi available at all — longest-match
    segmentation over space-delimited jyutping syllables, using the
    CC-Canto jyutping_index as the word list. A span the dictionary
    doesn't cover falls back to a single unmatched syllable (left for the
    LLM validation pass to reconsider, per SPEC.md §4 Step 2)."""
    syllables = jyutping_line.split()
    words: list[str] = []
    i = 0
    n = len(syllables)
    while i < n:
        matched_length = 0
        for length in range(min(max_word_syllables, n - i), 0, -1):
            candidate_key = "".join(syllables[i : i + length])
            if dictionary.lookup(jyutping=candidate_key):
                matched_length = length
                break
        if matched_length == 0:
            matched_length = 1
        words.append(" ".join(syllables[i : i + matched_length]))
        i += matched_length
    return words
