"""Read/write access to data/vocab_store.json plus the global status
state machine from SPEC.md §5.

    new (not yet in store)
      └─ on first review, unclicked → known
      └─ on first review, clicked   → learning
    learning ──(manually promoted)──> learned
    known / learning / learned ──(clicked again in a later dialogue)──> learning

Status is tracked globally per canonical word id, not per-dialogue.
"""

import json
from datetime import date

from app.config import VOCAB_STORE_PATH
from app.models.dialogue import StoredDialogue
from app.models.vocab import DefinitionSource, Occurrence, VocabEntry, VocabStatus


# --- pure transition functions (no I/O; unit-testable in isolation) ---


def on_click(current: VocabEntry | None) -> VocabStatus:
    """Clicking a word always flags it as still-being-studied, regardless
    of its prior status (or having no prior status at all)."""
    return VocabStatus.LEARNING


def on_unclicked_at_finish_review(current: VocabEntry | None) -> VocabStatus:
    """A word left unclicked when Finish Review is hit. Brand-new words
    default to known (unmarked = already known at the time the dialogue
    was processed). Words that already have a status are left unchanged —
    not being clicked *this time* must not downgrade an existing
    learning/learned word back to known."""
    if current is None:
        return VocabStatus.KNOWN
    return current.status


def promote_to_learned(current: VocabEntry) -> VocabStatus:
    """Manual promotion, once the user feels solid on a learning word."""
    return VocabStatus.LEARNED


def on_unclick(current: VocabEntry) -> VocabStatus:
    """Clicking a flagged word's own bullet entry removes the flag — the
    user already knows it (they were just re-checking the definition),
    so it goes back to known rather than staying in the learning list."""
    return VocabStatus.KNOWN


# --- storage ---


def _load_raw() -> dict[str, dict]:
    if not VOCAB_STORE_PATH.exists():
        return {}
    with VOCAB_STORE_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def _save_raw(data: dict[str, dict]) -> None:
    VOCAB_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with VOCAB_STORE_PATH.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)


def load_all() -> dict[str, VocabEntry]:
    return {word_id: VocabEntry(**raw) for word_id, raw in _load_raw().items()}


def get(word_id: str) -> VocabEntry | None:
    raw = _load_raw().get(word_id)
    return VocabEntry(**raw) if raw else None


def save(entry: VocabEntry) -> VocabEntry:
    data = _load_raw()
    data[entry.id] = entry.model_dump(mode="json")
    _save_raw(data)
    return entry


def record_click(
    word_id: str,
    *,
    dialogue_id: str,
    line_id: str,
    hanzi: str | None,
    jyutping: str,
    definition: str | None = None,
    source_of_definition: DefinitionSource | None = None,
) -> VocabEntry:
    """Apply the on_click transition and persist it, creating the entry
    if this word has never been seen before."""
    current = get(word_id)
    today = date.today().isoformat()
    new_status = on_click(current)

    if current is None:
        entry = VocabEntry(
            id=word_id,
            hanzi=hanzi,
            definition=definition,
            source_of_definition=source_of_definition,
            status=new_status,
            first_seen_dialogue_id=dialogue_id,
            first_seen_date=today,
            last_seen_date=today,
            times_seen=1,
            occurrences=[
                Occurrence(dialogue_id=dialogue_id, line_id=line_id, snippet=jyutping)
            ],
        )
    else:
        entry = current.model_copy(
            update={
                "status": new_status,
                "definition": definition or current.definition,
                "source_of_definition": source_of_definition
                or current.source_of_definition,
                "last_seen_date": today,
                "times_seen": current.times_seen + 1,
            }
        )
    return save(entry)


def update_definition(
    word_id: str, *, definition: str, source_of_definition: DefinitionSource | None
) -> VocabEntry:
    """Overwrites a word's cached definition — used when the user flags an
    existing definition as wrong and asks to re-resolve it. Unlike
    record_click, this never touches status/times_seen: re-evaluating a
    definition isn't a study interaction, just a correction."""
    current = get(word_id)
    if current is None:
        raise ValueError(f"No vocab entry for {word_id!r}")
    updated = current.model_copy(
        update={"definition": definition, "source_of_definition": source_of_definition}
    )
    return save(updated)


def unclick(word_id: str) -> VocabEntry:
    current = get(word_id)
    if current is None:
        raise ValueError(f"No vocab entry for {word_id!r}")
    updated = current.model_copy(update={"status": on_unclick(current)})
    return save(updated)


def promote(word_id: str) -> VocabEntry:
    current = get(word_id)
    if current is None:
        raise ValueError(f"No vocab entry for {word_id!r}")
    updated = current.model_copy(update={"status": promote_to_learned(current)})
    return save(updated)


def delete(word_id: str) -> None:
    data = _load_raw()
    data.pop(word_id, None)
    _save_raw(data)


def finish_review(dialogue: StoredDialogue, clicked_word_ids: set[str]) -> None:
    """Commit final statuses for every word in a dialogue at Finish Review
    time. Clicked words are already `learning` from record_click at
    click-time, so this only needs to handle the *unclicked* words:
    brand-new ones become `known`; words that already have a status are
    left untouched (see on_unclicked_at_finish_review)."""
    today = date.today().isoformat()
    seen: set[str] = set()
    for line in dialogue.lines:
        for token in line.words:
            if token.word_id in seen or token.word_id in clicked_word_ids:
                continue
            seen.add(token.word_id)

            current = get(token.word_id)
            if current is not None:
                continue  # unchanged, per on_unclicked_at_finish_review

            save(
                VocabEntry(
                    id=token.word_id,
                    hanzi=token.hanzi,
                    status=on_unclicked_at_finish_review(None),
                    first_seen_dialogue_id=dialogue.id,
                    first_seen_date=today,
                    last_seen_date=today,
                    times_seen=1,
                    occurrences=[
                        Occurrence(
                            dialogue_id=dialogue.id,
                            line_id=line.id,
                            snippet=token.jyutping,
                        )
                    ],
                )
            )
