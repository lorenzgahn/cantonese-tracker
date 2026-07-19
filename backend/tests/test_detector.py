"""Validates the input-type auto-detector against all 4 real/hand-crafted
sample fixtures used throughout this project — not synthetic strings
built to make the heuristics look good."""

from pathlib import Path

from app.services.detector import InputType, detect_input_type

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


def test_detects_structured_pdf_by_filename():
    assert detect_input_type(filename="sample_structured_dialogue.pdf") == InputType.STRUCTURED_PDF
    assert detect_input_type(filename="anything.PDF") == InputType.STRUCTURED_PDF


def test_detects_real_hanzi_narrative_sample():
    text = _read("sample_hanzi_narrative.txt")
    assert detect_input_type(text=text) == InputType.HANZI_NARRATIVE


def test_detects_real_legacy_annotated_sample():
    text = _read("sample_legacy_annotated.txt")
    assert detect_input_type(text=text) == InputType.LEGACY_ANNOTATED


def test_detects_real_plain_jyutping_sample():
    text = _read("sample_plain_jyutping.txt")
    assert detect_input_type(text=text) == InputType.PLAIN_JYUTPING


def test_pdf_filename_wins_even_with_text_also_present():
    # A file upload always carries a filename; text-content heuristics
    # should never override that a .pdf file was actually uploaded.
    assert (
        detect_input_type(text=_read("sample_hanzi_narrative.txt"), filename="upload.pdf")
        == InputType.STRUCTURED_PDF
    )


def test_hanzi_narrative_without_scene_markers_still_detected_as_type_4():
    # No [N] markers at all — should still fall through to Type 4 since
    # it's the only type that expects raw hanzi paste.
    assert detect_input_type(text="呢個係測試句子，冇任何場景標記。") == InputType.HANZI_NARRATIVE


def test_bracket_groups_without_definitions_are_not_legacy_annotated():
    # Has jyutping-looking brackets, but no trailing "key: definition"
    # lines — must not be misclassified as Type 3.
    text = "nei5 [hou2 noi6] mou5 gin3 laa3"
    assert detect_input_type(text=text) == InputType.PLAIN_JYUTPING


def test_empty_input_is_unknown():
    assert detect_input_type(text="") == InputType.UNKNOWN
    assert detect_input_type(text="   \n  ") == InputType.UNKNOWN
    assert detect_input_type() == InputType.UNKNOWN
