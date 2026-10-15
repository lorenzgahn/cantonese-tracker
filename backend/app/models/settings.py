from pydantic import BaseModel, Field


class Settings(BaseModel):
    """Global, app-wide preferences persisted in data/settings.json —
    not tied to any one dialogue."""

    # How many flagged words accumulate on the Review page before a
    # "Review past N words" flashcard checkpoint is offered.
    review_chunk_size: int = Field(default=15, ge=1, le=200)
