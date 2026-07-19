"""Type 3 importer: the user's existing hand-annotated format — plain
jyutping text (no hanzi) with `[bracketed]` multi-syllable words the user
didn't know, each followed by a trailing `key: definition` line. No
hanzi at all, so the non-bracketed portions go through the same
jyutping-trie segmentation as Type 2 (SPEC.md §4 Step 2).

Unlike every other importer, status is committed at IMPORT TIME rather
than interactively through Review (SPEC.md Phase 7 plan): a bracketed
word's manual definition is applied immediately via
`vocab_store.record_click` — mirroring exactly what a live click would
do, since bracketing *is* the user's already-performed "I don't know
this" flag — and every other (non-bracketed) word is committed via
`vocab_store.finish_review`'s existing "unclicked = known unless already
tracked" semantics, reused directly rather than reimplemented. This is
the same machinery Review's "Finish Review" button calls.
"""

import re
from dataclasses import dataclass
from datetime import date

from app.models.dialogue import StoredDialogue, StoredLine, StoredWordToken
from app.models.vocab import DefinitionSource
from app.services import vocab_store
from app.services.segmentation import (
    JYUTPING_SYLLABLE_PATTERN,
    compute_word_id,
    segment_jyutping_trie,
)

_BRACKET_PATTERN = re.compile(r"\[([^\]]+)\]")
_DEFINITION_LINE_PATTERN = re.compile(r"^([a-zA-Z0-9][a-zA-Z0-9 ]*?):\s*(.+)$")
_SPEAKER_PREFIX_PATTERN = re.compile(r"^([A-Z][a-zA-Z]*)\s+(.+)$")
_EDGE_PUNCTUATION = ".,!?;:…\"'「」()"


@dataclass
class ParsedLine:
    speaker: str | None
    text: str  # jyutping, brackets still embedded, speaker prefix stripped
    definitions: dict[str, str]  # bracket key (as written) -> definition


def _keys_match(definition_key: str, bracket_key: str) -> bool:
    def_syllables = definition_key.lower().split()
    bracket_syllables = bracket_key.lower().split()
    if def_syllables == bracket_syllables:
        return True
    # Tolerates the definition line dropping a leading syllable from the
    # bracketed phrase — a real mismatch found in the actual sample data,
    # not a hypothetical: bracket "[jat1 dyun6]" was later defined as
    # "dyun6: period", not "jat1 dyun6: period".
    return (
        0 < len(def_syllables) < len(bracket_syllables)
        and bracket_syllables[-len(def_syllables) :] == def_syllables
    )


def _find_matching_bracket_key(definition_key: str, expected_keys_remaining: list[str]) -> str | None:
    """A definition line's key must match one of the still-unresolved
    bracket keys from the current dialogue line — that's what
    distinguishes it from a short dialogue line that merely happens to
    contain a colon (e.g. a quoted "Nei5: ...")."""
    return next((k for k in expected_keys_remaining if _keys_match(definition_key, k)), None)


def parse_legacy_annotated(text: str) -> list[ParsedLine]:
    raw_lines = [line.strip() for line in text.splitlines()]
    raw_lines = [line for line in raw_lines if line]

    parsed: list[ParsedLine] = []
    i = 0
    while i < len(raw_lines):
        line = raw_lines[i]
        i += 1

        bracket_keys = _BRACKET_PATTERN.findall(line)
        definitions: dict[str, str] = {}
        remaining = list(bracket_keys)

        while remaining and i < len(raw_lines):
            m = _DEFINITION_LINE_PATTERN.match(raw_lines[i])
            if not m:
                break
            def_key, definition = m.group(1).strip(), m.group(2).strip()
            matched_bracket_key = _find_matching_bracket_key(def_key, remaining)
            if matched_bracket_key is None:
                break
            # Stored under the full original bracket key (not the
            # possibly-partial definition-line key), so _tokenize_line's
            # lookup by bracket_key finds it.
            definitions[matched_bracket_key] = definition
            remaining.remove(matched_bracket_key)
            i += 1

        speaker = None
        speaker_match = _SPEAKER_PREFIX_PATTERN.match(line)
        if speaker_match:
            speaker, line = speaker_match.group(1), speaker_match.group(2)

        parsed.append(ParsedLine(speaker=speaker, text=line, definitions=definitions))

    return parsed


def _tokenize_plain_jyutping(text: str) -> list[str]:
    """Groups a bracket-free chunk of jyutping text into words via the
    dictionary trie (Type 2 path). A token that isn't jyutping at all
    (an interjection like "Um", or code-switched English with no tone
    digit) is kept as its own standalone word rather than silently
    dropped — SPEC.md's "never silently drop content" principle,
    established for Type 1's Latin-script handling, applies here too."""
    raw_tokens = [tok.strip(_EDGE_PUNCTUATION) for tok in text.split()]
    raw_tokens = [tok for tok in raw_tokens if tok]

    words: list[str] = []
    batch: list[str] = []

    def flush_batch() -> None:
        if batch:
            words.extend(segment_jyutping_trie(" ".join(batch)))
            batch.clear()

    for tok in raw_tokens:
        if JYUTPING_SYLLABLE_PATTERN.fullmatch(tok):
            batch.append(tok)
        else:
            flush_batch()
            words.append(tok)
    flush_batch()
    return words


def _tokenize_line(parsed_line: ParsedLine) -> list[tuple[str, str | None]]:
    """Returns (word, definition_or_None) pairs in order — definition is
    set only for bracketed (manually annotated) words."""
    tokens: list[tuple[str, str | None]] = []
    pos = 0
    for m in _BRACKET_PATTERN.finditer(parsed_line.text):
        before = parsed_line.text[pos : m.start()]
        for word in _tokenize_plain_jyutping(before):
            tokens.append((word, None))

        bracket_key = m.group(1)
        definition = parsed_line.definitions.get(bracket_key, "")
        tokens.append((bracket_key, definition))
        pos = m.end()

    tail = parsed_line.text[pos:]
    for word in _tokenize_plain_jyutping(tail):
        tokens.append((word, None))

    return tokens


def build_stored_dialogue(dialogue_id: str, title: str, raw_text: str) -> StoredDialogue:
    parsed_lines = parse_legacy_annotated(raw_text)
    lines: list[StoredLine] = []
    clicked_word_ids: set[str] = set()

    for i, parsed_line in enumerate(parsed_lines):
        line_id = f"line-{i}"
        tokens: list[StoredWordToken] = []

        for j, (word, definition) in enumerate(_tokenize_line(parsed_line)):
            word_id = compute_word_id(word, None)
            tokens.append(
                StoredWordToken(token_id=f"{line_id}-w{j}", word_id=word_id, jyutping=word, hanzi=None)
            )
            if definition is not None:
                clicked_word_ids.add(word_id)
                vocab_store.record_click(
                    word_id,
                    dialogue_id=dialogue_id,
                    line_id=line_id,
                    hanzi=None,
                    jyutping=word,
                    definition=definition,
                    source_of_definition=DefinitionSource.MANUAL,
                )

        lines.append(StoredLine(id=line_id, speaker=parsed_line.speaker, words=tokens))

    dialogue = StoredDialogue(
        id=dialogue_id,
        title=title,
        lines=lines,
        source_type="legacy_annotated",
        imported_at=date.today().isoformat(),
    )
    # Commits every non-bracketed word as known (if it's brand new) —
    # reuses the exact same state-machine call the Review screen's
    # "Finish Review" button makes.
    vocab_store.finish_review(dialogue, clicked_word_ids)
    return dialogue


def import_legacy_annotated(raw_text: str, dialogue_id: str, title: str) -> StoredDialogue:
    return build_stored_dialogue(dialogue_id, title, raw_text)
