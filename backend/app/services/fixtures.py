"""Hand-written fixture data for Phase 0/1 — proves the storage + review
pipeline end-to-end before any real importer exists. Seeds a real
StoredDialogue (data/dialogues/demo.json) and a handful of vocab_store
entries, idempotently, on first access only.
"""

from app.models.dialogue import StoredDialogue, StoredLine, StoredWordToken
from app.models.vocab import DefinitionSource, VocabEntry, VocabStatus
from app.services import dialogue_store, vocab_store

_DEMO_DIALOGUE = StoredDialogue(
    id="demo",
    title="Hiking in Hong Kong (fixture excerpt)",
    lines=[
        StoredLine(
            id="line-1",
            speaker="Karen",
            words=[
                StoredWordToken(token_id="line-1-w0", word_id="zeoi3gan6", jyutping="zeoi3 gan6", hanzi="最近"),
                StoredWordToken(token_id="line-1-w1", word_id="hou2noi6mou5gin3", jyutping="hou2 noi6 mou5 gin3", hanzi="好耐冇見"),
                StoredWordToken(token_id="line-1-w2", word_id="nei5", jyutping="nei5", hanzi="你"),
                StoredWordToken(token_id="line-1-w3", word_id="laa3", jyutping="laa3", hanzi="喇"),
            ],
        ),
        StoredLine(
            id="line-2",
            speaker="Natalie",
            words=[
                StoredWordToken(token_id="line-2-w0", word_id="hai6aa3", jyutping="hai6 aa3", hanzi="係呀"),
                StoredWordToken(token_id="line-2-w1", word_id="heoi3zo2", jyutping="heoi3 zo2", hanzi="去咗"),
                StoredWordToken(token_id="line-2-w2", word_id="haang4saan1", jyutping="haang4 saan1", hanzi="行山"),
                StoredWordToken(token_id="line-2-w3", word_id="lo1", jyutping="lo1", hanzi="囉"),
            ],
        ),
        # Deliberately NOT in _DEMO_VOCAB_SEED below — these two words have
        # no vocab_store entry until clicked, so clicking them exercises
        # the real Step 3 path (Phase 3): dictionary hit for 好耐, and the
        # graceful-degradation placeholder for 難度 (confirmed absent from
        # CC-Canto) while the LLM fallback is blocked on `ant auth login`.
        StoredLine(
            id="line-3",
            speaker="Karen",
            words=[
                StoredWordToken(token_id="line-3-w0", word_id="hou2noi6", jyutping="hou2 noi6", hanzi="好耐"),
                StoredWordToken(token_id="line-3-w1", word_id="naan4dou6", jyutping="naan4 dou6", hanzi="難度"),
            ],
        ),
    ],
)

_DEMO_VOCAB_SEED: dict[str, tuple[str, VocabStatus]] = {
    "zeoi3gan6": ("recently", VocabStatus.KNOWN),
    "hou2noi6mou5gin3": ("long time no see", VocabStatus.KNOWN),
    "nei5": ("you", VocabStatus.KNOWN),
    "laa3": ("sentence-final particle", VocabStatus.KNOWN),
    "hai6aa3": ("yes / indeed", VocabStatus.KNOWN),
    "heoi3zo2": ("went (past tense of 'go')", VocabStatus.LEARNING),
    "haang4saan1": ("to hike", VocabStatus.KNOWN),
    "lo1": ("sentence-final particle (resigned tone)", VocabStatus.KNOWN),
}


def ensure_demo_seeded() -> None:
    if dialogue_store.load_stored("demo") is None:
        dialogue_store.save_stored(_DEMO_DIALOGUE)

    for word_id, (definition, status) in _DEMO_VOCAB_SEED.items():
        if vocab_store.get(word_id) is None:
            vocab_store.save(
                VocabEntry(
                    id=word_id,
                    definition=definition,
                    source_of_definition=DefinitionSource.MANUAL,
                    status=status,
                    first_seen_dialogue_id="demo",
                    times_seen=1,
                )
            )
