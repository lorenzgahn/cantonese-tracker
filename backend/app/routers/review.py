from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from app.models.dialogue import Dialogue
from app.models.vocab import VocabEntry
from app.services import definitions, dialogue_store, dictionary, fixtures, vocab_store

router = APIRouter(prefix="/api/dialogues", tags=["review"])


@router.get("", response_model=list[Dialogue])
def list_dialogues() -> list[Dialogue]:
    return dialogue_store.list_dialogues()


@router.get("/{dialogue_id}/export", response_class=PlainTextResponse)
def export_dialogue(dialogue_id: str) -> str:
    """SPEC.md §4 Step 1's deliverable: a clean, speaker-labelled,
    jyutping-only document — the artifact the user used to build by hand
    before even opening ChatGPT."""
    dialogue = dialogue_store.get_dialogue(dialogue_id)
    if dialogue is None:
        raise HTTPException(status_code=404, detail="Dialogue not found")

    blocks = []
    for line in dialogue.lines:
        text = " ".join(w.jyutping for w in line.words)
        blocks.append(f"{line.speaker}\n{text}" if line.speaker else text)
    return "\n\n".join(blocks)


@router.get("/{dialogue_id}", response_model=Dialogue)
def get_dialogue(dialogue_id: str) -> Dialogue:
    if dialogue_id == "demo":
        fixtures.ensure_demo_seeded()

    dialogue = dialogue_store.get_dialogue(dialogue_id)
    if dialogue is None:
        raise HTTPException(status_code=404, detail="Dialogue not found")
    return dialogue


@router.delete("/{dialogue_id}")
def delete_dialogue(dialogue_id: str) -> dict[str, str]:
    if dialogue_store.load_stored(dialogue_id) is None:
        raise HTTPException(status_code=404, detail="Dialogue not found")
    dialogue_store.delete_stored(dialogue_id)
    return {"status": "ok"}


class SetLinkRequest(BaseModel):
    url: str | None = None


@router.post("/{dialogue_id}/link", response_model=Dialogue)
def set_dialogue_link(dialogue_id: str, body: SetLinkRequest) -> Dialogue:
    """Sets, edits, or clears (empty/omitted url) this dialogue's link to
    its original audio/video/source content — settable at import time,
    or added/edited retroactively here for dialogues imported before this
    existed."""
    try:
        dialogue_store.set_link_url(dialogue_id, body.url)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return dialogue_store.get_dialogue(dialogue_id)


@router.post("/{dialogue_id}/words/{word_id}/click", response_model=VocabEntry)
def click_word(dialogue_id: str, word_id: str) -> VocabEntry:
    stored = dialogue_store.load_stored(dialogue_id)
    if stored is None:
        raise HTTPException(status_code=404, detail="Dialogue not found")

    line = next((l for l in stored.lines if any(w.word_id == word_id for w in l.words)), None)
    if line is None:
        raise HTTPException(status_code=404, detail="Word not found in this dialogue")
    token = next(w for w in line.words if w.word_id == word_id)

    # Step 3: resolve_word_definition decides whether this word's
    # definition is cacheable globally (unambiguous) or needs a fresh,
    # this-dialogue-scoped resolution (ambiguous) — see its docstring.
    line_context = " ".join(w.jyutping for w in line.words)
    definition, source_of_definition = dialogue_store.resolve_word_definition(
        dialogue_id,
        word_id,
        hanzi=token.hanzi,
        jyutping=token.jyutping,
        line_context=line_context,
        english_context=line.english,
    )

    return vocab_store.record_click(
        word_id,
        dialogue_id=dialogue_id,
        line_id=line.id,
        hanzi=token.hanzi,
        jyutping=token.jyutping,
        definition=definition,
        source_of_definition=source_of_definition,
    )


@router.post("/{dialogue_id}/words/{word_id}/reevaluate", response_model=Dialogue)
def reevaluate_word(dialogue_id: str, word_id: str) -> Dialogue:
    """Discards whatever definition is currently shown for this word *in
    this dialogue* and resolves a fresh one — for when the user knows
    it's wrong. Unlike click_word, this deliberately skips the cache
    check (that's the whole point of "re-evaluate"). Writes to this
    dialogue's own override — not the global default — whenever the
    word is genuinely ambiguous (matching resolve_word_definition's
    routing) or it already has an override, so a document-specific sense
    stays document-specific; otherwise refreshes the global default,
    same as before. The ambiguity check also catches words cached under
    the old blind-first-sense behavior, migrating them to a per-dialogue
    override the first time they're re-evaluated post-fix."""
    stored = dialogue_store.load_stored(dialogue_id)
    if stored is None:
        raise HTTPException(status_code=404, detail="Dialogue not found")

    line = next((l for l in stored.lines if any(w.word_id == word_id for w in l.words)), None)
    if line is None:
        raise HTTPException(status_code=404, detail="Word not found in this dialogue")
    token = next(w for w in line.words if w.word_id == word_id)

    line_context = " ".join(w.jyutping for w in line.words)
    definition, source_of_definition = definitions.resolve_definition(
        hanzi=token.hanzi, jyutping=token.jyutping, line_context=line_context, english_context=line.english
    )

    hits = dictionary.lookup(hanzi=token.hanzi, jyutping=token.jyutping)
    is_ambiguous = len(definitions.flatten_candidate_definitions(hits)) > 1

    if word_id in stored.definition_overrides or is_ambiguous:
        dialogue_store.set_definition_override(dialogue_id, word_id, definition)
    else:
        try:
            vocab_store.update_definition(word_id, definition=definition, source_of_definition=source_of_definition)
        except ValueError:
            raise HTTPException(status_code=404, detail="No vocab entry for this word")

    return dialogue_store.get_dialogue(dialogue_id)


class SetDefinitionOverrideRequest(BaseModel):
    definition: str


@router.post("/{dialogue_id}/words/{word_id}/definition", response_model=Dialogue)
def set_word_definition_override(dialogue_id: str, word_id: str, body: SetDefinitionOverrideRequest) -> Dialogue:
    """Overwrites word_id's definition for *this dialogue only* — for
    when the same jyutping means something different here than its
    shared default (see dialogue_store.set_definition_override). Every
    other dialogue keeps showing the global default untouched."""
    try:
        dialogue_store.set_definition_override(dialogue_id, word_id, body.definition)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return dialogue_store.get_dialogue(dialogue_id)


@router.post("/{dialogue_id}/lines/{line_id}/words/{word_id}/merge-next", response_model=Dialogue)
def merge_with_next_word(dialogue_id: str, line_id: str, word_id: str) -> Dialogue:
    """Fixes a bad segmentation by merging word_id with the next token in
    its line (e.g. "li1" + "paai4" → "li1paai4", 呢排, "lately"), then
    resolves a definition for the merged word same as a fresh click."""
    try:
        stored, merged_word_id = dialogue_store.merge_adjacent_tokens(dialogue_id, line_id, word_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    line = next(l for l in stored.lines if l.id == line_id)
    token = next(w for w in line.words if w.word_id == merged_word_id)
    line_context = " ".join(w.jyutping for w in line.words)

    definition, source_of_definition = dialogue_store.resolve_word_definition(
        dialogue_id,
        merged_word_id,
        hanzi=token.hanzi,
        jyutping=token.jyutping,
        line_context=line_context,
        english_context=line.english,
    )

    vocab_store.record_click(
        merged_word_id,
        dialogue_id=dialogue_id,
        line_id=line_id,
        hanzi=token.hanzi,
        jyutping=token.jyutping,
        definition=definition,
        source_of_definition=source_of_definition,
    )
    return dialogue_store.get_dialogue(dialogue_id)


@router.post("/{dialogue_id}/lines/{line_id}/words/{word_id}/split", response_model=Dialogue)
def split_word(dialogue_id: str, line_id: str, word_id: str) -> Dialogue:
    """Undoes an accidental merge by exploding word_id into one token per
    syllable, then resolves+flags a definition for each new piece (same
    cache-then-resolve flow as click_word) so they're immediately visible
    as bullets with a "merge with next" action, ready to be rejoined."""
    try:
        stored, new_tokens = dialogue_store.split_token(dialogue_id, line_id, word_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    line = next(l for l in stored.lines if l.id == line_id)
    line_context = " ".join(w.jyutping for w in line.words)

    for token in new_tokens:
        definition, source_of_definition = dialogue_store.resolve_word_definition(
            dialogue_id,
            token.word_id,
            hanzi=token.hanzi,
            jyutping=token.jyutping,
            line_context=line_context,
            english_context=line.english,
        )
        vocab_store.record_click(
            token.word_id,
            dialogue_id=dialogue_id,
            line_id=line_id,
            hanzi=token.hanzi,
            jyutping=token.jyutping,
            definition=definition,
            source_of_definition=source_of_definition,
        )

    return dialogue_store.get_dialogue(dialogue_id)


class EditJyutpingRequest(BaseModel):
    jyutping: str


@router.post("/{dialogue_id}/lines/{line_id}/words/{word_id}/jyutping", response_model=Dialogue)
def edit_word_jyutping(dialogue_id: str, line_id: str, word_id: str, body: EditJyutpingRequest) -> Dialogue:
    """Corrects a wrong reading (e.g. "dung6" should have been "tung4") —
    a different problem from merge/split, which fix word *boundaries*,
    not the reading itself. Since word_id is jyutping-derived, this
    changes the word's identity; the old definition carries over to the
    corrected word_id as an immediate placeholder (unless the corrected
    id already has its own entry from elsewhere, in which case that
    existing entry is left alone) — but it's still the *old* reading's
    definition. dialogue_store.edit_token_jyutping clears the token's
    hanzi for exactly this reason: it's no longer trustworthy as a
    lookup key, so hitting re-evaluate afterwards resolves a fresh
    definition from the corrected jyutping instead of re-finding the
    same stale one via the old hanzi."""
    old_entry = vocab_store.get(word_id)
    try:
        _stored, new_token = dialogue_store.edit_token_jyutping(dialogue_id, line_id, word_id, body.jyutping)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    if vocab_store.get(new_token.word_id) is None:
        vocab_store.record_click(
            new_token.word_id,
            dialogue_id=dialogue_id,
            line_id=line_id,
            hanzi=new_token.hanzi,
            jyutping=new_token.jyutping,
            definition=old_entry.definition if old_entry else None,
            source_of_definition=old_entry.source_of_definition if old_entry else None,
        )
    return dialogue_store.get_dialogue(dialogue_id)


@router.post("/{dialogue_id}/words/{word_id}/unclick", response_model=VocabEntry)
def unclick_word(dialogue_id: str, word_id: str) -> VocabEntry:
    """Clicking a word's own bullet entry (rather than the inline span)
    removes its learning flag — status is global per word_id (see
    dialogue_store.join_with_vocab), so dialogue_id isn't needed to find
    the entry; it's only here for URL symmetry with the click endpoint."""
    try:
        return vocab_store.unclick(word_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="No vocab entry for this word")


class FinishReviewRequest(BaseModel):
    clicked_word_ids: list[str]


@router.post("/{dialogue_id}/finish-review")
def finish_review(dialogue_id: str, body: FinishReviewRequest) -> dict[str, str]:
    stored = dialogue_store.load_stored(dialogue_id)
    if stored is None:
        raise HTTPException(status_code=404, detail="Dialogue not found")

    vocab_store.finish_review(stored, set(body.clicked_word_ids))
    return {"status": "ok"}
