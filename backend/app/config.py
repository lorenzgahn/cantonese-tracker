from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR / "data"
DIALOGUES_DIR = DATA_DIR / "dialogues"
VOCAB_STORE_PATH = DATA_DIR / "vocab_store.json"
DICTIONARY_PATH = DATA_DIR / "dictionary.json"

ANTHROPIC_MODEL = "claude-sonnet-5"
