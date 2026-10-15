from fastapi import APIRouter

from app.models.settings import Settings
from app.services import settings_store

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=Settings)
def get_settings() -> Settings:
    return settings_store.load()


@router.put("", response_model=Settings)
def update_settings(body: Settings) -> Settings:
    return settings_store.save(body)
