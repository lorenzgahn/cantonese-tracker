"""Validates the Type 1 (structured PDF) importer against the real
8-page "Hiking in Hong Kong" sample — not a synthetic PDF. Two real,
non-obvious PDF-extraction issues were caught and fixed this way (see
pdf_parser.py's module docstring):

  1. A speaker turn spanning a page break gets split into two table
     fragments by pdfplumber, not a clean new 3-row table.
  2. This PDF's embedded font encodes some hanzi (e.g. 行, 山) as Kangxi
     Radical codepoints instead of standard CJK ideographs — fixed with
     NFKC normalization.
"""

from collections import Counter
from pathlib import Path

import pytest

from app.services import dictionary
from app.services import pdf_parser
from app.services.pdf_parser import (
    ImportResult,
    build_stored_dialogue,
    extract_raw_rows,
    import_structured_pdf,
    parse_structured_pdf,
    reconcile_flagged_lines,
    reconstruct_turns,
)
from app.models.dialogue import StoredDialogue, StoredLine, StoredWordToken
from app.services.segmentation import compute_word_id

SAMPLE_PDF = Path(__file__).parent / "fixtures" / "sample_structured_dialogue.pdf"


@pytest.fixture(scope="module", autouse=True)
def _load_dictionary():
    if not dictionary.is_loaded():
        dictionary.load()


@pytest.fixture(autouse=True)
def _no_real_llm_calls(monkeypatch):
    """Every test in this file must never hit the real network — the LLM
    reconciliation pass is tested explicitly below with canned responses.
    Without this, test_import_structured_pdf_end_to_end would silently make
    a real, billed API call every test run."""
    monkeypatch.setattr(pdf_parser.llm, "validate_segmentation_batch", lambda flagged: {})


@pytest.fixture(scope="module")
def raw_rows():
    return extract_raw_rows(str(SAMPLE_PDF))


@pytest.fixture(scope="module")
def turns(raw_rows):
    return reconstruct_turns(raw_rows)


def test_extract_raw_rows_excludes_vocabulary_appendix(raw_rows):
    # The appendix is a 3-column table (word | jyutping | definition);
    # dialogue rows are always 2 columns. A stray "hiking; treking" or
    # "to hike" showing up as a bare row (rather than inside a turn's
    # jyutping/english field) would mean the appendix leaked in.
    assert all(len(row) == 2 for row in raw_rows)


def test_reconstruct_turns_matches_manual_count(turns):
    # Manually counted from the real transcript: 41 speaker turns,
    # alternating (not strictly) between exactly 2 speakers.
    assert len(turns) == 41
    assert {t.speaker for t in turns} == {"Karen", "Natalie"}


def test_reconstruct_turns_stitches_page_break_split_cell(turns):
    # Natalie's "因為首先要有班朋友..." turn has its hanzi cell split
    # across a page boundary by pdfplumber — must be reassembled into one
    # continuous turn, not truncated or duplicated.
    turn = next(t for t in turns if t.hanzi.startswith("因為首先要有班朋友"))
    assert "所以我就" in turn.hanzi or "song3 heoi3 haang4" in turn.jyutping.lower()
    assert turn.speaker == "Natalie"


def test_reconstruct_turns_normalizes_kangxi_radicals(turns):
    # 行山 ("to hike") — this PDF's font encodes 行/山 here as Kangxi
    # Radical codepoints (U+2F8F/U+2F2D), not standard CJK ideographs
    # (U+884C/U+5C71). Standard codepoints are required for every
    # downstream dictionary/segmentation lookup to work at all.
    karen_hiking_turn = next(t for t in turns if t.hanzi == "行山?")
    assert karen_hiking_turn.hanzi == "行山?"
    for ch in "行山":
        assert ord(ch) in {0x884C, 0x5C71}


def test_reconstruct_turns_last_turn_has_no_appendix_bleed(turns):
    last = turns[-1]
    assert last.hanzi == "好。"
    assert last.jyutping == "Hou2."
    assert "haang4" not in last.jyutping.lower().split("hou2.")[-1]


def test_build_stored_dialogue_segments_clean_lines(turns):
    result = build_stored_dialogue("test-dialogue", "Test", turns)
    line0 = result.dialogue.lines[0]
    assert [w.hanzi for w in line0.words] == ["最近", "好耐", "冇", "見", "你", "喇", "你", "最近", "做", "咩", "呀"]
    assert line0.words[0].jyutping == "Zeoi3 gan6"
    # word_id is jyutping (normalized lowercase, SPEC.md §6) folded with
    # hanzi when known, so same-sounding-different-meaning words don't
    # collide (see jyutping_utils.compute_word_id).
    assert line0.words[0].word_id == compute_word_id("Zeoi3 gan6", "最近")


def test_build_stored_dialogue_flags_problematic_lines_instead_of_dropping_them(turns):
    result = build_stored_dialogue("test-dialogue", "Test", turns)

    # Two independent reasons a line gets set aside for the LLM pass:
    # code-switched Latin-script content (10, unchanged from before merge
    # detection existed), plus lines pycantonese aligned fine but whose
    # word boundaries look wrong (11, e.g. "禮拜日" — a real word CC-Canto
    # just doesn't have as a whole-word entry, same class of gap as
    # 星期日 in the hanzi-narrative sample).
    reasons = Counter(f["reason"] for f in result.flagged_lines)
    assert reasons == {"latin_script": 10, "suspicious_merge": 11}

    # A flagged line must still produce a token — the content is kept
    # (as one unsegmented line-level token), never silently dropped.
    flagged_line_ids = {f["line_id"] for f in result.flagged_lines}
    for line in result.dialogue.lines:
        if line.id in flagged_line_ids:
            assert len(line.words) == 1
            assert line.words[0].jyutping  # non-empty


def test_import_structured_pdf_end_to_end():
    result = import_structured_pdf(str(SAMPLE_PDF), "e2e-test", "Hiking in Hong Kong")
    assert result.dialogue.id == "e2e-test"
    assert len(result.dialogue.lines) == 41
    assert sum(len(line.words) for line in result.dialogue.lines) > 41  # real segmentation happened


def test_parse_structured_pdf_is_pure_and_repeatable():
    # Calling it twice on the same file should give identical results —
    # no hidden state/order dependency in table extraction.
    turns_a = parse_structured_pdf(str(SAMPLE_PDF))
    turns_b = parse_structured_pdf(str(SAMPLE_PDF))
    assert [t.hanzi for t in turns_a] == [t.hanzi for t in turns_b]


def _flagged_result() -> ImportResult:
    line = StoredLine(
        id="line-0",
        speaker="Karen",
        words=[
            StoredWordToken(token_id="line-0-w0", word_id="unresolved-line-0", jyutping="hiking", hanzi="hiking")
        ],
    )
    dialogue = StoredDialogue(id="d", title="t", lines=[line], source_type="structured_pdf")
    flagged = [{"line_id": "line-0", "speaker": "Karen", "hanzi": "hiking", "jyutping": "hiking", "reason": "latin_script"}]
    return ImportResult(dialogue=dialogue, flagged_lines=flagged)


def test_reconcile_flagged_lines_replaces_placeholder_with_segmented_tokens(monkeypatch):
    result = _flagged_result()
    monkeypatch.setattr(
        pdf_parser.llm,
        "validate_segmentation_batch",
        lambda flagged: {"line-0": [("行山", "haang4saan1", ""), ("呀", "aa3", "?")]},
    )

    reconcile_flagged_lines(result)

    line = result.dialogue.lines[0]
    assert [w.hanzi for w in line.words] == ["行山", "呀"]
    assert [w.jyutping for w in line.words] == ["haang4saan1", "aa3"]
    assert [w.trailing_punctuation for w in line.words] == ["", "?"]
    assert line.words[0].word_id == compute_word_id("haang4saan1", "行山")


def test_reconcile_flagged_lines_leaves_placeholder_on_llm_failure(monkeypatch):
    result = _flagged_result()

    def _raise(flagged):
        raise RuntimeError("network down")

    monkeypatch.setattr(pdf_parser.llm, "validate_segmentation_batch", _raise)

    reconcile_flagged_lines(result)

    line = result.dialogue.lines[0]
    assert [w.hanzi for w in line.words] == ["hiking"]


def test_reconcile_flagged_lines_leaves_placeholder_when_line_id_missing_from_response(monkeypatch):
    result = _flagged_result()
    monkeypatch.setattr(pdf_parser.llm, "validate_segmentation_batch", lambda flagged: {})

    reconcile_flagged_lines(result)

    line = result.dialogue.lines[0]
    assert [w.hanzi for w in line.words] == ["hiking"]


def test_import_structured_pdf_end_to_end_calls_reconciliation_for_flagged_lines(monkeypatch):
    captured = {}

    def _fake_validate(flagged):
        captured["flagged"] = flagged
        return {}

    monkeypatch.setattr(pdf_parser.llm, "validate_segmentation_batch", _fake_validate)

    import_structured_pdf(str(SAMPLE_PDF), "e2e-test", "Hiking in Hong Kong")

    assert len(captured["flagged"]) == 21
    assert Counter(f["reason"] for f in captured["flagged"]) == {"latin_script": 10, "suspicious_merge": 11}
