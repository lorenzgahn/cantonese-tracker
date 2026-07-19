from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.models.vocab import DefinitionSource, VocabEntry, VocabStatus
from app.services import vocab_store

router = APIRouter(prefix="/api/vocab", tags=["vocab"])

_SORT_KEYS = {
    "last_seen_date": lambda e: e.last_seen_date or "",
    "first_seen_date": lambda e: e.first_seen_date or "",
    "times_seen": lambda e: e.times_seen,
    "id": lambda e: e.id,
}


@router.get("", response_model=list[VocabEntry])
def list_vocab(status: VocabStatus | None = None, sort_by: str = "last_seen_date") -> list[VocabEntry]:
    entries = list(vocab_store.load_all().values())
    if status is not None:
        entries = [e for e in entries if e.status == status]

    key_fn = _SORT_KEYS.get(sort_by, _SORT_KEYS["last_seen_date"])
    return sorted(entries, key=key_fn, reverse=(sort_by != "id"))


@router.post("/{word_id}/promote", response_model=VocabEntry)
def promote_word(word_id: str) -> VocabEntry:
    try:
        return vocab_store.promote(word_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


class UpsertVocabRequest(BaseModel):
    hanzi: str | None = None
    definition: str | None = None
    status: VocabStatus = VocabStatus.KNOWN
    user_notes: str | None = None


@router.put("/{word_id}", response_model=VocabEntry)
def upsert_word(word_id: str, body: UpsertVocabRequest) -> VocabEntry:
    """Manual add/edit — Vocab Dashboard's "add a word by hand" and
    "correct a definition" actions."""
    current = vocab_store.get(word_id)
    entry = VocabEntry(
        id=word_id,
        hanzi=body.hanzi if body.hanzi is not None else (current.hanzi if current else None),
        definition=body.definition,
        source_of_definition=DefinitionSource.MANUAL,
        status=body.status,
        first_seen_dialogue_id=current.first_seen_dialogue_id if current else None,
        first_seen_date=current.first_seen_date if current else None,
        last_seen_date=current.last_seen_date if current else None,
        times_seen=current.times_seen if current else 0,
        occurrences=current.occurrences if current else [],
        user_notes=body.user_notes if body.user_notes is not None else (current.user_notes if current else None),
    )
    return vocab_store.save(entry)


@router.delete("/{word_id}")
def delete_word(word_id: str) -> dict[str, str]:
    vocab_store.delete(word_id)
    return {"status": "ok"}
