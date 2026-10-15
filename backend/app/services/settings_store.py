"""Read/write access to data/settings.json — a single flat object of
global preferences (see models/settings.py). A missing file just means
"all defaults", so nothing needs seeding."""

import json

from app.config import SETTINGS_PATH
from app.models.settings import Settings


def load() -> Settings:
    if not SETTINGS_PATH.exists():
        return Settings()
    with SETTINGS_PATH.open("r", encoding="utf-8") as f:
        return Settings(**json.load(f))


def save(settings: Settings) -> Settings:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SETTINGS_PATH.open("w", encoding="utf-8") as f:
        json.dump(settings.model_dump(mode="json"), f, ensure_ascii=False, indent=2, sort_keys=True)
    return settings
