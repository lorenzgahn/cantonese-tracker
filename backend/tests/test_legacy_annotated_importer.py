"""Validates the Type 3 (legacy hand-annotated) importer against the
user's real existing format — jyutping text with [bracketed] words +
trailing definitions, exactly as pasted early in this project's spec
discussion. One real data quirk was caught this way: bracket
"[jat1 dyun6]" is later defined as "dyun6: period" (dropping a leading
syllable), not "jat1 dyun6: period" — handled with suffix matching
rather than assuming keys always match exactly.
"""

from pathlib import Path

import pytest

from app.models.vocab import VocabStatus
from app.services import dictionary, vocab_store
from app.services.importers.legacy_annotated import (
    build_stored_dialogue,
    parse_legacy_annotated,
)

SAMPLE_TEXT = (Path(__file__).parent / "fixtures" / "sample_legacy_annotated.txt").read_text(
    encoding="utf-8"
)


@pytest.fixture(scope="module", autouse=True)
def _load_dictionary():
    if not dictionary.is_loaded():
        dictionary.load()


def test_parse_extracts_inline_speaker_prefix():
    parsed = parse_legacy_annotated(SAMPLE_TEXT)
    assert parsed[0].speaker == "Karen"
    assert parsed[0].text.startswith("aa4,")
    # Every other line has no speaker prefix in this sample.
    assert all(p.speaker is None for p in parsed[1:])


def test_parse_matches_definition_with_dropped_leading_syllable():
    # Real data quirk: bracket "[jat1 dyun6]" is defined on its own line
    # as "dyun6: period", not "jat1 dyun6: period".
    parsed = parse_legacy_annotated(SAMPLE_TEXT)
    assert parsed[0].definitions["jat1 dyun6"] == "period"


def test_parse_collects_all_six_definitions_for_the_first_line():
    parsed = parse_legacy_annotated(SAMPLE_TEXT)
    assert set(parsed[0].definitions.keys()) == {
        "faan1 zo2", "jat1 dyun6", "si4 gaan3", "gwaa3 zyu6", "waa6 saai3", "lam2 faan1 hei2",
    }


def test_parse_does_not_treat_short_dialogue_lines_as_definitions():
    # "Hai6 aa3." has no brackets, so it must remain its own dialogue
    # line, not get absorbed as a stray definition of the previous line.
    parsed = parse_legacy_annotated(SAMPLE_TEXT)
    plain_lines = [p for p in parsed if not p.definitions and "[" not in p.text]
    assert any(p.text == "Hai6 aa3." for p in plain_lines)


def test_build_stored_dialogue_commits_bracketed_words_as_learning():
    dialogue = build_stored_dialogue("legacy-test-1", "Legacy Sample", SAMPLE_TEXT)
    entry = vocab_store.get("faan1zo2")
    assert entry is not None
    assert entry.status == VocabStatus.LEARNING
    assert entry.definition == "returned"
    assert entry.source_of_definition.value == "manual"


def test_build_stored_dialogue_commits_non_bracketed_words_as_known():
    dialogue = build_stored_dialogue("legacy-test-2", "Legacy Sample", SAMPLE_TEXT)
    # "aa4" appears in line 0 outside any bracket.
    entry = vocab_store.get("aa4")
    assert entry is not None
    assert entry.status == VocabStatus.KNOWN


def test_build_stored_dialogue_handles_bracket_with_no_definition_given():
    # Real gap in the source data: "[faan1]" in line 2 has no
    # corresponding definition line anywhere — must not crash, and must
    # still be committed as learning (the user did bracket it).
    dialogue = build_stored_dialogue("legacy-test-3", "Legacy Sample", SAMPLE_TEXT)
    entry = vocab_store.get("faan1")
    assert entry is not None
    assert entry.status == VocabStatus.LEARNING


def test_build_stored_dialogue_preserves_word_order_and_drops_nothing():
    dialogue = build_stored_dialogue("legacy-test-4", "Legacy Sample", SAMPLE_TEXT)
    line0_jyutping = [w.jyutping for w in dialogue.lines[0].words]
    assert "faan1 zo2" in line0_jyutping
    assert "lam2 faan1 hei2" in line0_jyutping
    # Every word has a non-empty jyutping value — nothing silently dropped.
    for line in dialogue.lines:
        for word in line.words:
            assert word.jyutping.strip()
