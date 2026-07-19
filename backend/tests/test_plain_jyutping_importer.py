"""Validates the Type 2 (plain jyutping, no hanzi) importer. Reuses the
jyutping-trie segmentation already validated against real data in Phase
4/8 — this file's job is checking the importer's own wiring (line
splitting, flagging, word_id normalization), not re-proving the trie.

One real bug surfaced here that also affected every other importer: the
dictionary index lookup was case-sensitive, so a sentence-initial
capitalized word (every real sample seen so far capitalizes the first
word of a line — "Zeoi3 gan6", "Haang4 saan1?") silently missed on every
lookup. Fixed in the shared normalize_jyutping_key.
"""

from pathlib import Path

import pytest

from app.services import dictionary
from app.services.importers.plain_jyutping import build_stored_dialogue

SAMPLE_TEXT = (Path(__file__).parent / "fixtures" / "sample_plain_jyutping.txt").read_text(
    encoding="utf-8"
)


@pytest.fixture(scope="module", autouse=True)
def _load_dictionary():
    if not dictionary.is_loaded():
        dictionary.load()


def test_build_stored_dialogue_one_line_per_input_line():
    result = build_stored_dialogue("plain-test", "Plain Sample", SAMPLE_TEXT)
    assert len(result.dialogue.lines) == 4
    assert all(line.speaker is None for line in result.dialogue.lines)


def test_case_insensitive_dictionary_lookup_groups_sentence_initial_words():
    # "Haang4 saan1" (capitalized, sentence-initial) must group exactly
    # like the lowercase "haang4 saan1" already validated in Phase 4 —
    # this is the regression check for the case-sensitivity bug.
    result = build_stored_dialogue("plain-test", "Plain Sample", SAMPLE_TEXT)
    scene2 = result.dialogue.lines[2]
    assert [w.jyutping for w in scene2.words] == ["Haang4 saan1"]


def test_word_id_is_lowercase_regardless_of_display_capitalization():
    result = build_stored_dialogue("plain-test", "Plain Sample", SAMPLE_TEXT)
    scene2 = result.dialogue.lines[2]
    assert scene2.words[0].word_id == "haang4saan1"
    assert scene2.words[0].jyutping == "Haang4 saan1"  # display form unchanged


def test_flags_words_with_no_dictionary_entry():
    result = build_stored_dialogue("plain-test", "Plain Sample", SAMPLE_TEXT)
    assert any(f["jyutping"] == "mui5" for f in result.flagged_words)
    assert all(f["reason"] == "no_dictionary_match" for f in result.flagged_words)


def test_never_drops_a_syllable():
    result = build_stored_dialogue("plain-test", "Plain Sample", SAMPLE_TEXT)
    for line, original in zip(result.dialogue.lines, SAMPLE_TEXT.strip().splitlines()):
        total_syllables = sum(len(w.jyutping.split()) for w in line.words)
        assert total_syllables == len(original.split())
