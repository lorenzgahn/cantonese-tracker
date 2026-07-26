"""Validates the Type 1a (hanzi-only narrative) importer against the real
"新雨褸" (New Raincoat) sample story — not synthetic text. This is the
first importer where the LLM pass is genuinely load-bearing: real,
confirmed CC-Canto coverage gaps show up even for ordinary vocabulary
(喺 "at/in", 期 as in 星期 "week", 青蛙 "frog"), not just slang.
"""

from pathlib import Path

import pytest

from app.services import dictionary
from app.services.importers import hanzi_narrative
from app.services.importers.hanzi_narrative import (
    ImportResult,
    build_stored_dialogue,
    generate_word_jyutping,
    import_hanzi_narrative,
    reconcile_flagged_lines,
    reconcile_unresolved_words,
    split_scenes,
)
from app.models.dialogue import StoredDialogue, StoredLine, StoredWordToken
from app.services.segmentation import compute_word_id

SAMPLE_TEXT = (Path(__file__).parent / "fixtures" / "sample_hanzi_narrative.txt").read_text(
    encoding="utf-8"
)


@pytest.fixture(scope="module", autouse=True)
def _load_dictionary():
    if not dictionary.is_loaded():
        dictionary.load()


@pytest.fixture(autouse=True)
def _no_real_llm_calls(monkeypatch):
    """Every test in this file must never hit the real network — the LLM
    reconciliation passes are tested explicitly below with canned
    responses. Without this, any test calling import_hanzi_narrative()
    would silently make a real, billed API call every test run. Both LLM
    entry points used by this importer must be stubbed here:
    generate_jyutping_batch (word-level) and validate_segmentation_batch
    (scene-level, for suspicious-merge re-segmentation)."""
    monkeypatch.setattr(hanzi_narrative.llm, "generate_jyutping_batch", lambda words: {})
    monkeypatch.setattr(hanzi_narrative.llm, "validate_segmentation_batch", lambda flagged: {})


def test_split_scenes_finds_all_markers_including_title():
    scenes = split_scenes(SAMPLE_TEXT)
    markers = [m for m, _block in scenes]
    assert markers == ["0", "2", "3", "4", "5", "6", "7", "8", "9", "10"]
    assert scenes[0][1] == "新雨褸"  # the title block


def test_split_scenes_strips_whitespace_and_skips_empty_blocks():
    scenes = split_scenes("[0]標題\n\n[2]\n\n[3]內容")
    # scene 2's block is empty (just whitespace) and must be dropped, not
    # produce an empty Line.
    assert [m for m, _ in scenes] == ["0", "3"]


def test_split_scenes_handles_lettered_sub_markers():
    # Real user input: a numbered scene can be subdivided into lettered
    # sub-scenes ([1a], [1b]) — each is its own chunk, distinct from a
    # bare [1]/[2]. A continuation line with no marker of its own (the
    # indented "阿樂笑。剪得唔靚啊！" line) stays attached to the
    # preceding marker's block rather than starting a new one.
    text = (
        "[0]個個都唔一樣\n\n"
        "[1a]呢個係阿樂，佢嘅頭髮好長，要剪喇。\n"
        "[1b]媽媽話：「我幫你剪頭髮啦。」\n"
        "      阿樂笑。剪得唔靚啊！\n\n"
        "[2a]同學仔都笑佢，阿樂喊。\n"
        "[2b]老師話：「我哋唔應該笑人㗎。"
    )
    scenes = split_scenes(text)
    assert [m for m, _block in scenes] == ["0", "1a", "1b", "2a", "2b"]

    _marker, block_1b = scenes[2]
    assert "媽媽話" in block_1b
    assert "阿樂笑" in block_1b  # continuation line merged into 1b, not dropped


def test_generate_word_jyutping_dictionary_hit():
    # 行山 confirmed in CC-Canto during Phase 4/5 — same dictionary, same
    # confidence tier.
    result = generate_word_jyutping("行山")
    assert result.confidence == "dictionary"
    assert result.jyutping == "haang4 saan1"


def test_generate_word_jyutping_per_character_fallback():
    # 文仔 (the character's name) is not a CC-Canto entry, but both 文 and
    # 仔 resolve individually — confirmed via REPL during Phase 6.
    result = generate_word_jyutping("文仔")
    assert result.confidence == "per_character"
    assert result.jyutping == "man2 zai2"


def test_generate_word_jyutping_unresolved_when_a_character_is_missing():
    # 期 (as in 星期 "week") has no CC-Canto entry at all, standalone or
    # otherwise — confirmed via REPL. A word containing it can't even
    # fall back to per-character concatenation.
    result = generate_word_jyutping("星期")
    assert result.confidence == "unresolved"
    assert result.jyutping == ""


def test_build_stored_dialogue_produces_one_line_per_scene():
    result = build_stored_dialogue("test-narrative", "New Raincoat", SAMPLE_TEXT)
    assert len(result.dialogue.lines) == 10
    assert [line.id for line in result.dialogue.lines] == [
        "scene-0", "scene-2", "scene-3", "scene-4", "scene-5",
        "scene-6", "scene-7", "scene-8", "scene-9", "scene-10",
    ]
    # No speaker structure in this input type — every line must be null.
    assert all(line.speaker is None for line in result.dialogue.lines)


def test_build_stored_dialogue_flags_a_suspected_merge_at_the_whole_scene_level():
    result = build_stored_dialogue("test-narrative", "New Raincoat", SAMPLE_TEXT)

    # 星期日 lives in scene-2 alongside 新雨褸 — pycantonese actually glues
    # 新 "new" onto 雨褸 "raincoat" here (confirmed via REPL), so the whole
    # scene is set aside for LLM re-segmentation rather than trusting the
    # per-word dictionary path on a bad split.
    merge_flags = [f for f in result.flagged_lines if f["reason"] == "suspicious_merge"]
    scene2_flag = next(f for f in merge_flags if f["line_id"] == "scene-2")
    assert "星期日" in scene2_flag["hanzi"]

    # A flagged scene must still produce a token (never dropped) with a
    # placeholder that's visually distinguishable from real jyutping —
    # at scene granularity here, not per-word, since word boundaries
    # aren't trustworthy for it yet.
    scene2 = next(line for line in result.dialogue.lines if line.id == "scene-2")
    assert len(scene2.words) == 1
    assert scene2.words[0].jyutping == f"[{scene2_flag['hanzi']}]"


def test_build_stored_dialogue_never_drops_a_word():
    result = build_stored_dialogue("test-narrative", "New Raincoat", SAMPLE_TEXT)
    for line in result.dialogue.lines:
        for word in line.words:
            assert word.jyutping  # every token has *something* displayable
            assert word.word_id


def test_build_stored_dialogue_flagged_word_reasons_are_only_the_two_known_kinds():
    result = build_stored_dialogue("test-narrative", "New Raincoat", SAMPLE_TEXT)
    reasons = {f["reason"] for f in result.flagged_words}
    assert reasons <= {"per_character_fallback_used", "no_dictionary_match"}
    assert len(result.flagged_words) > 0  # this sample genuinely needs the LLM pass


def _unresolved_result() -> ImportResult:
    line = StoredLine(
        id="scene-2",
        speaker=None,
        words=[
            StoredWordToken(token_id="scene-2-w0", word_id="unresolved-scene-2-w0", jyutping="[星期日]", hanzi="星期日"),
            StoredWordToken(token_id="scene-2-w1", word_id="haang4saan1", jyutping="haang4 saan1", hanzi="行山"),
        ],
    )
    dialogue = StoredDialogue(id="d", title="t", lines=[line], source_type="hanzi_narrative")
    flagged = [{"line_id": "scene-2", "hanzi": "星期日", "reason": "no_dictionary_match"}]
    return ImportResult(dialogue=dialogue, flagged_words=flagged)


def test_reconcile_unresolved_words_replaces_placeholder_with_generated_jyutping(monkeypatch):
    result = _unresolved_result()
    monkeypatch.setattr(
        hanzi_narrative.llm, "generate_jyutping_batch", lambda words: {"星期日": "sing1kei4jat6"}
    )

    reconcile_unresolved_words(result)

    line = result.dialogue.lines[0]
    assert line.words[0].jyutping == "sing1kei4jat6"
    assert line.words[0].word_id == compute_word_id("sing1kei4jat6", "星期日")
    # The already-resolved neighbor must be untouched.
    assert line.words[1].jyutping == "haang4 saan1"


def test_reconcile_unresolved_words_leaves_placeholder_on_llm_failure(monkeypatch):
    result = _unresolved_result()

    def _raise(words):
        raise RuntimeError("network down")

    monkeypatch.setattr(hanzi_narrative.llm, "generate_jyutping_batch", _raise)

    reconcile_unresolved_words(result)

    assert result.dialogue.lines[0].words[0].jyutping == "[星期日]"


def test_reconcile_unresolved_words_leaves_placeholder_when_word_missing_from_response(monkeypatch):
    result = _unresolved_result()
    monkeypatch.setattr(hanzi_narrative.llm, "generate_jyutping_batch", lambda words: {})

    reconcile_unresolved_words(result)

    assert result.dialogue.lines[0].words[0].jyutping == "[星期日]"


def test_reconcile_unresolved_words_noop_when_nothing_flagged(monkeypatch):
    line = StoredLine(
        id="scene-2", speaker=None,
        words=[StoredWordToken(token_id="scene-2-w0", word_id="haang4saan1", jyutping="haang4 saan1", hanzi="行山")],
    )
    dialogue = StoredDialogue(id="d", title="t", lines=[line], source_type="hanzi_narrative")
    result = ImportResult(dialogue=dialogue, flagged_words=[])

    called = False

    def _fail_if_called(words):
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(hanzi_narrative.llm, "generate_jyutping_batch", _fail_if_called)
    reconcile_unresolved_words(result)
    assert not called


def test_import_hanzi_narrative_end_to_end_resolves_flagged_words_via_mocked_llm(monkeypatch):
    # Every word in this real sample that's unresolved standalone (not
    # just per-character-fallback) ends up folded into a scene flagged as
    # a suspected merge instead (see the scene-2 test above) — so this
    # sample text has nothing left to exercise generate_jyutping_batch on.
    # That reconciliation path is tested directly (with a synthetic
    # fixture) in the tests above; this test exercises the real sample's
    # actual code path instead: scene-level re-segmentation.
    monkeypatch.setattr(
        hanzi_narrative.llm,
        "validate_segmentation_batch",
        lambda flagged: {"scene-2": [("星期日", "sing1kei4jat6", ""), ("其餘", "kei4jyu4", "")]},
    )

    result = import_hanzi_narrative(SAMPLE_TEXT, "test-narrative", "New Raincoat")

    scene2 = next(line for line in result.dialogue.lines if line.id == "scene-2")
    assert [w.hanzi for w in scene2.words] == ["星期日", "其餘"]
    assert scene2.words[0].jyutping == "sing1kei4jat6"
    assert scene2.words[0].word_id == compute_word_id("sing1kei4jat6", "星期日")
