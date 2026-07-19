import pytest

from app.services import vocab_store


@pytest.fixture(autouse=True)
def isolated_vocab_store(tmp_path, monkeypatch):
    """Every test gets its own throwaway vocab_store.json, so tests never
    touch (or depend on) the real data/vocab_store.json."""
    monkeypatch.setattr(vocab_store, "VOCAB_STORE_PATH", tmp_path / "vocab_store.json")
