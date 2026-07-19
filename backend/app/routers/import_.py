import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.services import detector, dialogue_store, pdf_parser
from app.services.importers import hanzi_narrative, legacy_annotated, plain_jyutping

router = APIRouter(prefix="/api/import", tags=["import"])


class DetectInputTypeRequest(BaseModel):
    text: str | None = None
    filename: str | None = None


@router.post("/detect")
def detect_input_type(body: DetectInputTypeRequest) -> dict:
    """Powers the Import screen's auto-detected mode selector — always
    paired with a manual override in the UI (Phase 9/10), since none of
    these heuristics are airtight."""
    detected = detector.detect_input_type(text=body.text, filename=body.filename)
    return {"detected_type": detected.value}


@router.post("/pdf")
async def import_pdf(
    file: UploadFile = File(...), series: str = Form("Other"), level: int | None = Form(None)
) -> dict:
    if file.filename is None or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Expected a .pdf file")

    dialogue_id = uuid.uuid4().hex[:8]
    title = Path(file.filename).stem

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        result = pdf_parser.import_structured_pdf(tmp_path, dialogue_id, title)
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    result.dialogue.series = series
    result.dialogue.level = level
    dialogue_store.save_stored(result.dialogue)

    return {
        "dialogue_id": dialogue_id,
        "title": title,
        "line_count": len(result.dialogue.lines),
        "flagged_line_count": len(result.flagged_lines),
        "flagged_lines": result.flagged_lines,
    }


class ImportHanziNarrativeRequest(BaseModel):
    text: str
    title: str = "Untitled"
    series: str = "Other"
    level: int | None = None


@router.post("/hanzi-narrative")
def import_hanzi_narrative_text(body: ImportHanziNarrativeRequest) -> dict:
    dialogue_id = uuid.uuid4().hex[:8]
    result = hanzi_narrative.import_hanzi_narrative(body.text, dialogue_id, body.title)
    result.dialogue.series = body.series
    result.dialogue.level = body.level
    dialogue_store.save_stored(result.dialogue)

    return {
        "dialogue_id": dialogue_id,
        "title": body.title,
        "line_count": len(result.dialogue.lines),
        "flagged_word_count": len(result.flagged_words),
        "flagged_words": result.flagged_words,
    }


class ImportLegacyAnnotatedRequest(BaseModel):
    text: str
    title: str = "Untitled"
    series: str = "Other"
    level: int | None = None


@router.post("/legacy-annotated")
def import_legacy_annotated_text(body: ImportLegacyAnnotatedRequest) -> dict:
    dialogue_id = uuid.uuid4().hex[:8]
    dialogue = legacy_annotated.import_legacy_annotated(body.text, dialogue_id, body.title)
    dialogue.series = body.series
    dialogue.level = body.level
    dialogue_store.save_stored(dialogue)

    return {
        "dialogue_id": dialogue_id,
        "title": body.title,
        "line_count": len(dialogue.lines),
        "word_count": sum(len(line.words) for line in dialogue.lines),
    }


class ImportPlainJyutpingRequest(BaseModel):
    text: str
    title: str = "Untitled"
    series: str = "Other"
    level: int | None = None


@router.post("/plain-jyutping")
def import_plain_jyutping_text(body: ImportPlainJyutpingRequest) -> dict:
    dialogue_id = uuid.uuid4().hex[:8]
    result = plain_jyutping.import_plain_jyutping(body.text, dialogue_id, body.title)
    result.dialogue.series = body.series
    result.dialogue.level = body.level
    dialogue_store.save_stored(result.dialogue)

    return {
        "dialogue_id": dialogue_id,
        "title": body.title,
        "line_count": len(result.dialogue.lines),
        "flagged_word_count": len(result.flagged_words),
        "flagged_words": result.flagged_words,
    }
