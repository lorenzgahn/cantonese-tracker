"""Runtime access to the CC-Canto dictionary built by etl/build_dictionary.py.
Loaded fully into memory once (see load()), not re-read per lookup — it's
static reference data, not something that needs a query engine.
"""

import json
from typing import TypedDict

from app.config import DICTIONARY_PATH
from app.services.jyutping_utils import normalize_jyutping_key


class DictRecord(TypedDict):
    traditional: str
    simplified: str
    jyutping: str
    definitions: list[str]


_hanzi_index: dict[str, list[DictRecord]] | None = None
_jyutping_index: dict[str, list[DictRecord]] | None = None


def load() -> None:
    global _hanzi_index, _jyutping_index
    if not DICTIONARY_PATH.exists():
        raise FileNotFoundError(
            f"{DICTIONARY_PATH} not found — run "
            "`backend/.venv/bin/python backend/etl/build_dictionary.py` first."
        )
    with DICTIONARY_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)
    _hanzi_index = data["hanzi_index"]
    _jyutping_index = data["jyutping_index"]


def is_loaded() -> bool:
    return _hanzi_index is not None


def lookup(hanzi: str | None = None, jyutping: str | None = None) -> list[DictRecord]:
    """Hanzi lookup is preferred when available — jyutping alone is
    ambiguous across homophones. Returns [] on a miss (a miss is the
    normal, expected trigger for the Step 3 LLM fallback, not an error)."""
    if _hanzi_index is None or _jyutping_index is None:
        raise RuntimeError("Dictionary not loaded — call dictionary.load() at startup.")

    if hanzi and hanzi in _hanzi_index:
        return _hanzi_index[hanzi]
    if jyutping:
        key = normalize_jyutping_key(jyutping)
        if key in _jyutping_index:
            return _jyutping_index[key]
    return []
