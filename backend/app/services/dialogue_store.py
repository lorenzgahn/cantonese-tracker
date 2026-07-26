"""Read/write access to data/dialogues/<id>.json, and the join between a
StoredDialogue (structural, immutable-once-imported) and the live global
vocab store that produces the API/frontend-facing Dialogue shape.

Joining at read time (rather than baking status into the stored file) is
what makes re-opening a dialogue reflect that word's *current* global
status — e.g. a word marked known while reviewing dialogue A, then
clicked while reviewing dialogue B, shows as `learning` if you go back
and re-open dialogue A, without dialogue A's stored file ever changing.
"""

import json

from app.config import DIALOGUES_DIR
from app.models.dialogue import Dialogue, Line, StoredDialogue, StoredWordToken, WordToken
from app.models.vocab import DefinitionSource, VocabStatus
from app.services import definitions, dictionary, vocab_store
from app.services.segmentation import compute_word_id


def _path(dialogue_id: str):
    return DIALOGUES_DIR / f"{dialogue_id}.json"


def load_stored(dialogue_id: str) -> StoredDialogue | None:
    path = _path(dialogue_id)
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return StoredDialogue(**json.load(f))


def save_stored(dialogue: StoredDialogue) -> None:
    DIALOGUES_DIR.mkdir(parents=True, exist_ok=True)
    with _path(dialogue.id).open("w", encoding="utf-8") as f:
        json.dump(dialogue.model_dump(mode="json"), f, ensure_ascii=False, indent=2)


def delete_stored(dialogue_id: str) -> None:
    _path(dialogue_id).unlink(missing_ok=True)


def set_link_url(dialogue_id: str, url: str | None) -> StoredDialogue:
    """Sets (or clears, if url is None/empty) the link to this dialogue's
    original audio/video/source content — settable at import time or
    added/edited later, since not every dialogue has one up front. Raises
    ValueError if the dialogue doesn't exist."""
    stored = load_stored(dialogue_id)
    if stored is None:
        raise ValueError(f"No dialogue {dialogue_id!r}")
    stored.link_url = url or None
    save_stored(stored)
    return stored


def set_definition_override(dialogue_id: str, word_id: str, definition: str) -> StoredDialogue:
    """Records a definition for word_id that only applies within this
    dialogue — for a jyutping that's shared globally but means something
    different here. join_with_vocab prefers this over the global
    vocab_store default for every occurrence of word_id in this dialogue;
    every other dialogue is unaffected. Raises ValueError if the dialogue
    doesn't exist."""
    stored = load_stored(dialogue_id)
    if stored is None:
        raise ValueError(f"No dialogue {dialogue_id!r}")
    stored.definition_overrides[word_id] = definition
    save_stored(stored)
    return stored


def resolve_word_definition(
    dialogue_id: str,
    word_id: str,
    *,
    hanzi: str | None,
    jyutping: str,
    line_context: str,
    english_context: str | None,
) -> tuple[str | None, DefinitionSource | None]:
    """The single place that decides *where* a word's definition gets
    cached: globally (the shared vocab_store default) for words with
    zero or one dictionary sense, or per-dialogue (definition_overrides)
    for genuinely ambiguous ones. This split exists because "same
    jyutping, same hanzi, but the correct sense depends on context"
    (e.g. 就 meaning "then" vs "right away") stops being resolvable by a
    single global cache once resolution is context-aware — a per-word
    definition history isn't needed for this: definition_overrides
    already *is* that storage, just keyed by dialogue instead of an
    ordered list.

    Idempotent within a dialogue: a word already resolved here (an
    existing override) is returned with no new LLM call. An unambiguous
    word still behaves exactly as before this feature existed — reuse
    the global cache if set, else resolve once and let the caller cache
    it globally via vocab_store.record_click, same as always.

    Returns (definition, source) for the caller to pass straight into
    vocab_store.record_click, unchanged from that function's existing
    contract. Raises ValueError if the dialogue doesn't exist."""
    stored = load_stored(dialogue_id)
    if stored is None:
        raise ValueError(f"No dialogue {dialogue_id!r}")

    override = stored.definition_overrides.get(word_id)
    if override is not None:
        return override, DefinitionSource.MANUAL

    hits = dictionary.lookup(hanzi=hanzi, jyutping=jyutping)
    is_ambiguous = len(definitions.flatten_candidate_definitions(hits)) > 1

    if not is_ambiguous:
        existing = vocab_store.get(word_id)
        if existing and existing.definition:
            return existing.definition, existing.source_of_definition
        return definitions.resolve_definition(
            hanzi=hanzi, jyutping=jyutping, line_context=line_context, english_context=english_context
        )

    # Ambiguous: always resolve fresh for *this* dialogue's context,
    # never silently reuse whatever some other dialogue's occurrence
    # happened to produce. Stamped MANUAL (not LLM) to match what
    # join_with_vocab will show on every later read of this override —
    # returning LLM here would make the very next page load disagree
    # with what this click just showed.
    definition, _source = definitions.resolve_definition(
        hanzi=hanzi, jyutping=jyutping, line_context=line_context, english_context=english_context
    )
    set_definition_override(dialogue_id, word_id, definition)
    return definition, DefinitionSource.MANUAL


def merge_adjacent_tokens(dialogue_id: str, line_id: str, word_id: str) -> tuple[StoredDialogue, str]:
    """Fixes a segmentation error where two adjacent tokens should have
    been one word — e.g. "li1" + "paai4" should be "li1paai4" (呢排,
    "lately"), not two separately-defined words. Merges word_id with the
    very next token in its line, persists the change to this dialogue's
    stored file, and returns the merged word's new id so the caller can
    resolve a fresh definition for it. Raises ValueError for any of:
    unknown dialogue, unknown line, unknown word, or word_id being the
    last token in its line (nothing to merge with)."""
    stored = load_stored(dialogue_id)
    if stored is None:
        raise ValueError(f"No dialogue {dialogue_id!r}")
    line = next((l for l in stored.lines if l.id == line_id), None)
    if line is None:
        raise ValueError(f"No line {line_id!r} in dialogue {dialogue_id!r}")
    idx = next((i for i, w in enumerate(line.words) if w.word_id == word_id), None)
    if idx is None:
        raise ValueError(f"No word {word_id!r} in line {line_id!r}")
    if idx + 1 >= len(line.words):
        raise ValueError("No next word to merge with")

    first, second = line.words[idx], line.words[idx + 1]
    merged_hanzi = ((first.hanzi or "") + (second.hanzi or "")) or None
    merged_jyutping = f"{first.jyutping} {second.jyutping}".strip()
    merged_word_id = compute_word_id(merged_jyutping, merged_hanzi) or f"unresolved-{line_id}-{idx}"

    merged_token = StoredWordToken(
        token_id=first.token_id, word_id=merged_word_id, jyutping=merged_jyutping, hanzi=merged_hanzi
    )
    line.words[idx : idx + 2] = [merged_token]
    save_stored(stored)
    return stored, merged_word_id


def split_token(dialogue_id: str, line_id: str, word_id: str) -> tuple[StoredDialogue, list[StoredWordToken]]:
    """Splits a merged token back into one token per syllable — the
    inverse of merge_adjacent_tokens, for undoing an accidental merge
    (whether from import-time segmentation or a manual merge). Always
    explodes all the way down to individual syllables rather than
    guessing at some partial regrouping — the original word boundaries
    aren't tracked anywhere once merged, so the user re-merges whichever
    adjacent pieces are actually correct by hand afterward. Raises
    ValueError for: unknown dialogue/line/word, or a token that's already
    a single syllable (nothing to split)."""
    stored = load_stored(dialogue_id)
    if stored is None:
        raise ValueError(f"No dialogue {dialogue_id!r}")
    line = next((l for l in stored.lines if l.id == line_id), None)
    if line is None:
        raise ValueError(f"No line {line_id!r} in dialogue {dialogue_id!r}")
    idx = next((i for i, w in enumerate(line.words) if w.word_id == word_id), None)
    if idx is None:
        raise ValueError(f"No word {word_id!r} in line {line_id!r}")

    token = line.words[idx]
    syllables = token.jyutping.split()
    if len(syllables) < 2:
        raise ValueError("Word is already a single syllable — nothing to split")

    # Only distribute hanzi per-syllable when the counts line up — a
    # mismatch (e.g. an embedded English word from a KEEP-style merge)
    # means we can't know which character goes with which syllable, so
    # leave hanzi unset rather than mis-map it. The frontend doesn't
    # display hanzi at all, so this only affects future dictionary
    # lookups keyed on it, not anything visible.
    hanzi_chars: list[str | None]
    if token.hanzi and len(token.hanzi) == len(syllables):
        hanzi_chars = list(token.hanzi)
    else:
        hanzi_chars = [None] * len(syllables)

    new_tokens = [
        StoredWordToken(
            token_id=f"{token.token_id}-s{i}",
            word_id=compute_word_id(syl, ch) or f"unresolved-{line_id}-{idx}-{i}",
            jyutping=syl,
            hanzi=ch,
        )
        for i, (syl, ch) in enumerate(zip(syllables, hanzi_chars))
    ]
    line.words[idx : idx + 1] = new_tokens
    save_stored(stored)
    return stored, new_tokens


def edit_token_jyutping(
    dialogue_id: str, line_id: str, word_id: str, new_jyutping: str
) -> tuple[StoredDialogue, StoredWordToken]:
    """Corrects a token's reading in place — for when the jyutping itself
    is wrong (e.g. "dung6" should have been "tung4"), as opposed to a
    word-boundary problem (see merge_adjacent_tokens/split_token for
    that). token_id is unchanged; word_id is recomputed from the
    corrected jyutping, since identity is jyutping-derived — this is
    effectively a rename, not a content edit. hanzi is cleared rather
    than carried over: dictionary.lookup() prefers a hanzi hit over a
    jyutping one, so keeping the old (wrong-reading) hanzi around would
    make a later re-evaluate resolve the stale definition all over again
    instead of one for the corrected reading. Raises ValueError for:
    unknown dialogue/line/word, or an empty replacement."""
    stored = load_stored(dialogue_id)
    if stored is None:
        raise ValueError(f"No dialogue {dialogue_id!r}")
    line = next((l for l in stored.lines if l.id == line_id), None)
    if line is None:
        raise ValueError(f"No line {line_id!r} in dialogue {dialogue_id!r}")
    idx = next((i for i, w in enumerate(line.words) if w.word_id == word_id), None)
    if idx is None:
        raise ValueError(f"No word {word_id!r} in line {line_id!r}")
    if not new_jyutping.strip():
        raise ValueError("New jyutping cannot be empty")

    token = line.words[idx]
    new_word_id = compute_word_id(new_jyutping, None) or f"unresolved-{line_id}-{idx}"
    corrected = StoredWordToken(
        token_id=token.token_id, word_id=new_word_id, jyutping=new_jyutping, hanzi=None
    )
    line.words[idx] = corrected
    save_stored(stored)
    return stored, corrected


def list_stored_ids() -> list[str]:
    if not DIALOGUES_DIR.exists():
        return []
    return sorted(p.stem for p in DIALOGUES_DIR.glob("*.json"))


def join_with_vocab(stored: StoredDialogue) -> Dialogue:
    """A word with no vocab entry yet is rendered as `known` — per spec
    §4 Step 3/4, a brand-new word is assumed known until the user clicks
    it; it isn't created in the vocab store just by being displayed.

    Status is always the global one — the same jyutping is either
    learning or it isn't, everywhere. Definition is different: the same
    jyutping can mean different things in different dialogues, so this
    dialogue's own definition_overrides (see set_definition_override)
    takes precedence over the global vocab_store default whenever one is
    set, on a per-word_id, per-dialogue basis."""
    entries = vocab_store.load_all()
    lines = []
    for stored_line in stored.lines:
        words = []
        for token in stored_line.words:
            entry = entries.get(token.word_id)
            override = stored.definition_overrides.get(token.word_id)
            if override is not None:
                definition, source_of_definition = override, DefinitionSource.MANUAL
            else:
                definition = entry.definition if entry else None
                source_of_definition = entry.source_of_definition if entry else None
            words.append(
                WordToken(
                    token_id=token.token_id,
                    word_id=token.word_id,
                    jyutping=token.jyutping,
                    hanzi=token.hanzi,
                    trailing_punctuation=token.trailing_punctuation,
                    status=entry.status if entry else VocabStatus.KNOWN,
                    definition=definition,
                    source_of_definition=source_of_definition,
                )
            )
        lines.append(Line(id=stored_line.id, speaker=stored_line.speaker, words=words))
    return Dialogue(
        id=stored.id,
        title=stored.title,
        lines=lines,
        source_type=stored.source_type,
        imported_at=stored.imported_at,
        series=stored.series,
        level=stored.level,
        link_url=stored.link_url,
    )


def get_dialogue(dialogue_id: str) -> Dialogue | None:
    stored = load_stored(dialogue_id)
    if stored is None:
        return None
    return join_with_vocab(stored)


def list_dialogues() -> list[Dialogue]:
    return [join_with_vocab(load_stored(dialogue_id)) for dialogue_id in list_stored_ids()]
