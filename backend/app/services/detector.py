"""Auto-detects which of the 4 input types (SPEC.md §3) a pasted text or
uploaded file is, so the Import screen can pre-select the right importer
— always with a manual override available, never hidden, since none of
these heuristics are airtight.

Priority order (file check first, then content heuristics from most to
least structurally distinctive):

1. Filename ends in `.pdf` -> structured PDF (Type 1).
2. Hanzi present AND numbered `[N]` scene markers present -> hanzi-only
   narrative (Type 4) — the marker pattern is unique to this type.
3. `[bracket]` groups whose *content* looks like jyutping (not just a
   bare number, which would be a Type-4 marker) AND `key: definition`
   trailing lines present -> legacy annotated (Type 3).
4. Hanzi present at all (no markers) -> still Type 4 — narrative text
   pasted without scene markers is the closest fit; the whole text
   becomes one block.
5. Otherwise (no hanzi anywhere) -> plain jyutping (Type 2), the
   residual/weakest-signal default.
"""

import re
from enum import Enum

from app.services.segmentation import JYUTPING_SYLLABLE_PATTERN, is_cjk_char

_SCENE_MARKER_PATTERN = re.compile(r"\[\d+\]")
_BRACKET_PATTERN = re.compile(r"\[([^\]]+)\]")
_DEFINITION_LINE_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9 ]*:\s*\S", re.MULTILINE)


class InputType(str, Enum):
    STRUCTURED_PDF = "structured_pdf"
    HANZI_NARRATIVE = "hanzi_narrative"
    LEGACY_ANNOTATED = "legacy_annotated"
    PLAIN_JYUTPING = "plain_jyutping"
    UNKNOWN = "unknown"


def _has_hanzi(text: str) -> bool:
    return any(is_cjk_char(ch) for ch in text)


def _has_jyutping_bracket_groups(text: str) -> bool:
    return any(JYUTPING_SYLLABLE_PATTERN.search(group) for group in _BRACKET_PATTERN.findall(text))


def detect_input_type(text: str | None = None, filename: str | None = None) -> InputType:
    if filename and filename.lower().endswith(".pdf"):
        return InputType.STRUCTURED_PDF

    if not text or not text.strip():
        return InputType.UNKNOWN

    has_hanzi = _has_hanzi(text)
    has_scene_markers = bool(_SCENE_MARKER_PATTERN.search(text))

    if has_hanzi and has_scene_markers:
        return InputType.HANZI_NARRATIVE

    if _has_jyutping_bracket_groups(text) and _DEFINITION_LINE_PATTERN.search(text):
        return InputType.LEGACY_ANNOTATED

    if has_hanzi:
        return InputType.HANZI_NARRATIVE

    return InputType.PLAIN_JYUTPING
