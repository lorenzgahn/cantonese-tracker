import pytest
from pydantic import ValidationError

from app.models.settings import Settings
from app.services import settings_store


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_store, "SETTINGS_PATH", tmp_path / "settings.json")


def test_missing_file_gives_defaults():
    assert settings_store.load().review_chunk_size == 15


def test_save_then_load_round_trips():
    settings_store.save(Settings(review_chunk_size=10))
    assert settings_store.load().review_chunk_size == 10


def test_chunk_size_must_be_positive():
    with pytest.raises(ValidationError):
        Settings(review_chunk_size=0)
