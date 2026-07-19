"""Validates the segmentation core against real lines from the "Hiking in
Hong Kong" sample dialogue — not synthetic strings. Two real bugs were
caught this way during Phase 4 (see segmentation.py's module docstring
and inline comments) before any importer got built on top of them:

  1. pycantonese's segmenter doesn't always cleanly separate an embedded
     '...' from adjacent hanzi — need to extract only the CJK characters
     from each token, not trust the token's raw length.
  2. Cantonese-specific particles like 㗎 live in CJK Extension A
     (U+3400-U+4DBF), not the main CJK block (U+4E00-U+9FFF) — a range
     check on the main block alone silently drops them.
  3. (Caught, not a code bug per se) filtering both sides down to
     CJK-only / tone-digit-only tokens means a code-switched word can
     vanish from both counts and the syllable count still coincidentally
     matches — Latin-script detection has to be an explicit, separate
     check, not inferred from a count mismatch.
"""

import pytest

from app.services import dictionary
from app.services.segmentation import (
    project_hanzi_to_jyutping,
    segment_jyutping_trie,
)


@pytest.fixture(scope="module", autouse=True)
def _load_dictionary():
    # Real dictionary.json built in Phase 2 — segment_jyutping_trie needs
    # it loaded; static reference data, safe to load once per test module.
    if not dictionary.is_loaded():
        dictionary.load()


# --- Type 1 path: hanzi + jyutping already both present, project one onto the other ---

REAL_CLEAN_LINES = [
    ("行山？", "Haang4 saan1?", [("行山", "Haang4 saan1")]),
    ("係呀。", "Hai6 aa3.", [("係", "Hai6"), ("呀", "aa3")]),
    ("九龍家嘛？", "Gau2 Lung4 gaa1 maa3?", [("九龍", "Gau2 Lung4"), ("家嘛", "gaa1 maa3")]),
    (
        # A real regression check: pycantonese originally returned "嗯...啱"
        # as one token (comma/ellipsis embedded mid-word); segment_hanzi
        # must split it back into two separate words at that punctuation
        # boundary, not glue 嗯+啱 together.
        "嗯...啱曬我。",
        "Ng6...Ngaam1 saai3 ngo5.",
        [("嗯", "Ng6"), ("啱", "Ngaam1"), ("曬", "saai3"), ("我", "ngo5")],
    ),
]


@pytest.mark.parametrize("hanzi,jyutping,expected_words", REAL_CLEAN_LINES)
def test_project_hanzi_to_jyutping_aligns_real_lines(hanzi, jyutping, expected_words):
    result = project_hanzi_to_jyutping(hanzi, jyutping)
    assert result.aligned
    assert [(w.hanzi, w.jyutping) for w in result.words] == expected_words


def test_project_hanzi_to_jyutping_long_real_line_with_rare_particle():
    """好...難行㗎啫 uses 㗎 (CJK Extension A) — regression test for the
    missed-character bug found during Phase 4."""
    hanzi = "都幾靚嘅，我都行過一次，都唔錯，同埋都唔係好難行㗎啫。"
    jyutping = (
        "Dou1 gei2 leng3 ge3, ngo5 dou1 haang4 gwo3 jat1 ci3, dou1 m4 co3, "
        "tung4 maai4 dou1 m4 hai6 hou2 naan4 haang4 gaa3 ze1."
    )
    result = project_hanzi_to_jyutping(hanzi, jyutping)
    assert result.aligned
    assert ("㗎", "gaa3") in [(w.hanzi, w.jyutping) for w in result.words]


def test_project_hanzi_to_jyutping_flags_code_switched_line():
    """A real line with embedded English (instagram, po) must be flagged
    for the LLM pass, not silently produce a wrong/incomplete result."""
    hanzi = "係呀我見到你 instagram 呢，嘩你 po 咗勁多相囉。"
    jyutping = (
        "Hai6 aa3 ngo5 gin3 dou2 nei5 INSTAGRAM ne1, waa3 nei5 PO zo2 "
        "ging6 do1 soeng2 lo1."
    )
    result = project_hanzi_to_jyutping(hanzi, jyutping)
    assert not result.aligned
    assert result.reason == "latin_script"
    assert result.words == []


def test_project_hanzi_to_jyutping_flags_genuine_syllable_mismatch():
    """A line where the jyutping is simply missing a syllable (no Latin
    script involved) must be flagged for the reason that's actually
    true — a count mismatch, not code-switching."""
    result = project_hanzi_to_jyutping("行山", "haang4")  # missing "saan1"
    assert not result.aligned
    assert result.reason == "syllable_count_mismatch"


# --- Type 2 path: jyutping only, no hanzi — longest-match against the dictionary ---


def test_jyutping_trie_groups_a_real_curated_idiom():
    # 好耐冇見 ("long time no see") is a real 4-syllable CC-Canto entry —
    # confirmed via REPL lookup during Phase 4, not assumed.
    assert segment_jyutping_trie("hou2 noi6 mou5 gin3") == ["hou2 noi6 mou5 gin3"]


def test_jyutping_trie_groups_a_two_syllable_word():
    assert segment_jyutping_trie("haang4 saan1") == ["haang4 saan1"]


def test_jyutping_trie_falls_back_to_single_syllables_when_dictionary_has_no_match():
    # 最近 ("recently") is confirmed absent from CC-Canto (Phase 4 REPL
    # check) — the trie should NOT crash or guess, just fall back to
    # unmatched single syllables for the LLM pass to reconsider later.
    assert segment_jyutping_trie("zeoi3 gan6") == ["zeoi3", "gan6"]


def test_jyutping_trie_handles_a_full_real_line():
    result = segment_jyutping_trie("hai6 aa3 ngo5 gin3 dou2 nei5")
    assert result == ["hai6 aa3", "ngo5", "gin3", "dou2", "nei5"]
    # Every original syllable must be preserved somewhere in the output —
    # segmentation groups syllables, it must never drop any.
    assert sum(len(w.split()) for w in result) == 6
