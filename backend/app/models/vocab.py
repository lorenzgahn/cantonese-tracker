from enum import Enum

from pydantic import BaseModel


class VocabStatus(str, Enum):
    KNOWN = "known"
    LEARNING = "learning"
    LEARNED = "learned"


class DefinitionSource(str, Enum):
    DICTIONARY = "dictionary"
    LLM = "llm"
    MANUAL = "manual"


class Occurrence(BaseModel):
    dialogue_id: str
    line_id: str
    snippet: str


class VocabEntry(BaseModel):
    id: str  # canonical key: normalized jyutping, spaces stripped, e.g. "faan1zo2"
    hanzi: str | None = None
    definition: str | None = None
    source_of_definition: DefinitionSource | None = None
    status: VocabStatus
    first_seen_dialogue_id: str | None = None
    first_seen_date: str | None = None
    last_seen_date: str | None = None
    times_seen: int = 0
    occurrences: list[Occurrence] = []
    user_notes: str | None = None
