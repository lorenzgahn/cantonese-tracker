from pydantic import BaseModel

from app.models.vocab import DefinitionSource, VocabStatus


class StoredWordToken(BaseModel):
    """The structural, immutable-once-imported shape persisted in
    data/dialogues/<id>.json. Deliberately carries no status/definition —
    those live only in the global vocab store and must always be joined
    in fresh at read time (see join_with_vocab in dialogue_store.py), or
    re-opening an old dialogue would show a stale snapshot instead of the
    word's current global status."""

    token_id: str  # unique within the dialogue, e.g. "line-1-w0"
    word_id: str  # canonical vocab key this token resolves to, e.g. "faan1zo2"
    jyutping: str
    hanzi: str | None = None
    # Punctuation immediately following this word in the source (".",
    # "...", "?", ...) — display-only. Deliberately excluded from word_id
    # (see jyutping_utils.compute_word_id) so the same word doesn't
    # fragment into a different vocab entry depending on whether this
    # particular occurrence happens to sit at a clause boundary.
    trailing_punctuation: str = ""


class StoredLine(BaseModel):
    id: str
    speaker: str | None = None
    words: list[StoredWordToken]
    # This turn's English translation, when the source provided one (PDF
    # imports only) — internal signal for definitions.resolve_definition,
    # deliberately never exposed to the frontend (WordToken/Dialogue have
    # no equivalent field; nothing renders it).
    english: str | None = None


class StoredDialogue(BaseModel):
    id: str
    title: str
    lines: list[StoredLine]
    source_type: str = "unknown"  # detector.InputType value, for the Dialogue Library
    imported_at: str = ""  # ISO date; defaulted for dialogues imported before this field existed
    series: str = "Other"  # which book/course this came from — "Hambaanglaang" | "Cantonese Conversations" | "Other"
    level: int | None = None  # Hambaanglaang's numbered level (1, 2, ...); blank for series without one
    definition_overrides: dict[str, str] = {}  # word_id -> this dialogue's own sense, when the shared default is wrong here
    link_url: str | None = None  # link to the original audio/video/source content, shown as "Link to Dialogue" on Review


class WordToken(BaseModel):
    """API/frontend-facing shape: a StoredWordToken denormalized with its
    *current* status from the global vocab store."""

    token_id: str
    word_id: str
    jyutping: str
    hanzi: str | None = None
    trailing_punctuation: str = ""
    status: VocabStatus
    definition: str | None = None
    source_of_definition: DefinitionSource | None = None


class Line(BaseModel):
    id: str
    speaker: str | None = None
    words: list[WordToken]


class Dialogue(BaseModel):
    id: str
    title: str
    lines: list[Line]
    source_type: str = "unknown"
    imported_at: str = ""
    series: str = "Other"
    level: int | None = None
    link_url: str | None = None
