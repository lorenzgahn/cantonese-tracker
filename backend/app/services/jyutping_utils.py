"""Tiny shared module so dictionary.py and segmentation.py don't import
each other directly (segmentation.segment_jyutping_trie calls
dictionary.lookup; dictionary.lookup needs this same normalization) —
keeping it here breaks that cycle."""


def normalize_jyutping_key(jyutping: str) -> str:
    """Canonical form used both as the dictionary's jyutping_index key
    and as a WordToken's word_id (SPEC.md §6/§5): spaces stripped and
    lowercased, e.g. 'Haang4 Saan1' -> 'haang4saan1'.

    Lowercasing matters in practice, not just in theory: sentence-initial
    words are capitalized in every real sample seen so far ("Zeoi3 gan6",
    "Haang4 saan1?", "Hai6 aa3."), and CC-Canto's own jyutping is all
    lowercase — without normalizing case, a dictionary-backed word at the
    start of a line would silently miss on every lookup.
    """
    return jyutping.replace(" ", "").lower()


def compute_word_id(jyutping: str, hanzi: str | None) -> str:
    """A word's identity for vocab status, definitions, and flagging —
    everywhere a StoredWordToken's word_id is assigned should go through
    this, not normalize_jyutping_key directly.

    The same jyutping can be two unrelated words (teng1 聽 "listen" vs
    teng1 廳 "living room"), so hanzi — when known — is folded into the
    id to keep them distinct: separate status, separate definitions,
    separate flagging, both within a dialogue and across dialogues.
    Falls back to jyutping alone when hanzi is unknown, since that's the
    best signal available (plain-jyutping input has no hanzi at all, so
    same-sounding words there are genuinely indistinguishable)."""
    key = normalize_jyutping_key(jyutping)
    if not key:
        return ""
    return f"{key}__{hanzi}" if hanzi else key
