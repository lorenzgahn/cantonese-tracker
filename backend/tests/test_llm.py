"""Covers validate_segmentation_batch's long-line pre-splitting and
size-based batching — added after a real transcript ("17 Snow's Year in
the Netherlands") had several flagged turns that were full monologues
(one 1,084 jyutping / 286 hanzi characters) and stayed unresolved even
with the earlier fixed-count chunking, because a single line that long
overran one call's output budget on its own. Real LLM calls only happen
inside _validate_segmentation_chunk, so the pure helpers around it
(_split_flagged_line, _pack_into_chunks, _reassemble_results) are tested
directly, and the end-to-end validate_segmentation_batch tests mock at
the _validate_segmentation_chunk boundary — matching the pattern every
other test file uses for llm.py's other batch functions."""

from app.services import llm


# --- _split_at ---


def test_split_at_is_a_lossless_partition():
    pieces = llm._split_at("Ng6...Ngaam1 saai3 ngo5.", llm._STRONG_SENTENCE_BOUNDARY)
    assert "".join(pieces) == "Ng6...Ngaam1 saai3 ngo5."
    assert pieces == ["Ng6...", "Ngaam1 saai3 ngo5."]


def test_split_at_returns_whole_text_when_pattern_never_matches():
    assert llm._split_at("no punctuation here", llm._STRONG_SENTENCE_BOUNDARY) == ["no punctuation here"]


# --- _split_flagged_line ---


def test_split_flagged_line_leaves_short_lines_untouched():
    assert llm._split_flagged_line("行山？", "Haang4 saan1?", max_len=80) == [("行山？", "Haang4 saan1?")]


def test_split_flagged_line_splits_long_line_at_sentence_boundaries():
    hanzi = "係囉。" * 20 + "唔係。" * 10  # well over 80 chars, two distinct sentences repeated
    jyutping = "Hai6 lo1." * 20 + "M4 hai6." * 10
    pieces = llm._split_flagged_line(hanzi, jyutping, max_len=80)

    assert len(pieces) > 1
    # lossless: reassembling every piece reproduces the original exactly
    assert "".join(h for h, _ in pieces) == hanzi
    assert "".join(j for _, j in pieces) == jyutping
    for h, _ in pieces:
        assert len(h) <= 80


def test_split_flagged_line_falls_back_when_hanzi_and_jyutping_sentence_counts_disagree():
    # Three hanzi sentences, but the jyutping hint only has two — can't
    # safely pair them, so the whole thing stays together rather than
    # risking a misaligned split.
    hanzi = "甲。" * 30 + "乙。" * 30 + "丙。" * 30
    jyutping = "Gaap3." * 30 + "Jyut6 Bing2." * 30  # only two sentence-final periods worth of structure
    pieces = llm._split_flagged_line(hanzi, jyutping, max_len=80)
    assert pieces == [(hanzi, jyutping)]


def test_split_flagged_line_falls_back_when_there_is_no_punctuation_at_all():
    hanzi = "冇標點" * 30
    pieces = llm._split_flagged_line(hanzi, "", max_len=80)
    assert pieces == [(hanzi, "")]


def test_split_flagged_line_falls_back_to_clause_punctuation_for_an_overlong_sentence():
    # One giant "sentence" (no sentence-ending punctuation until the very
    # end) but full of commas — should still split, just on the weaker
    # boundary.
    hanzi = "，".join(["甲乙丙丁"] * 30) + "。"
    jyutping = ", ".join(["gaap3 jyut6 bing2 ding1"] * 30) + "."
    pieces = llm._split_flagged_line(hanzi, jyutping, max_len=80)

    assert len(pieces) > 1
    assert "".join(h for h, _ in pieces) == hanzi
    assert "".join(j for _, j in pieces) == jyutping


def test_split_flagged_line_handles_empty_jyutping_hint():
    hanzi = "係囉。" * 20 + "唔係。" * 10
    pieces = llm._split_flagged_line(hanzi, "", max_len=80)
    assert len(pieces) > 1
    assert "".join(h for h, _ in pieces) == hanzi
    assert all(j == "" for _, j in pieces)


# --- _pack_into_chunks ---


def test_pack_into_chunks_groups_by_character_budget():
    items = [{"line_id": f"l{i}", "hanzi": "x" * 30} for i in range(5)]  # 30 chars each
    chunks = llm._pack_into_chunks(items, max_chars=70)
    # 30+30=60 fits, +30 more would be 90 > 70, so groups of 2/2/1
    assert [len(c) for c in chunks] == [2, 2, 1]


def test_pack_into_chunks_gives_an_oversized_item_its_own_chunk():
    items = [{"line_id": "l0", "hanzi": "x" * 500}, {"line_id": "l1", "hanzi": "y" * 10}]
    chunks = llm._pack_into_chunks(items, max_chars=100)
    assert [item["line_id"] for chunk in chunks for item in chunk] == ["l0", "l1"]
    assert len(chunks[0]) == 1


# --- _reassemble_results ---


def test_reassemble_results_concatenates_split_parts_in_order():
    prepared = [
        {"line_id": "line-7__part0", "hanzi": "a", "jyutping": "a", "_parent_line_id": "line-7"},
        {"line_id": "line-7__part1", "hanzi": "b", "jyutping": "b", "_parent_line_id": "line-7"},
    ]
    raw = {
        "line-7__part0": [("甲", "gaap3", "")],
        "line-7__part1": [("乙", "jyut6", ".")],
    }
    result = llm._reassemble_results(prepared, raw)
    assert result == {"line-7": [("甲", "gaap3", ""), ("乙", "jyut6", ".")]}


def test_reassemble_results_passes_through_an_unsplit_line():
    prepared = [{"line_id": "line-0", "hanzi": "a", "jyutping": "a", "_parent_line_id": "line-0"}]
    raw = {"line-0": [("行山", "haang4saan1", "?")]}
    assert llm._reassemble_results(prepared, raw) == {"line-0": [("行山", "haang4saan1", "?")]}


def test_reassemble_results_keeps_a_partially_resolved_lines_successful_parts():
    prepared = [
        {"line_id": "line-7__part0", "hanzi": "a", "jyutping": "a", "_parent_line_id": "line-7"},
        {"line_id": "line-7__part1", "hanzi": "b", "jyutping": "b", "_parent_line_id": "line-7"},
    ]
    raw = {"line-7__part0": [("甲", "gaap3", "")]}  # part1's chunk failed
    result = llm._reassemble_results(prepared, raw)
    assert result == {"line-7": [("甲", "gaap3", "")]}


# --- validate_segmentation_batch end-to-end (mocked at the chunk boundary) ---


def _flagged(n: int) -> list[dict]:
    return [{"line_id": f"line-{i}", "hanzi": f"hanzi-{i}", "jyutping": f"jyutping-{i}"} for i in range(n)]


def test_validate_segmentation_batch_packs_short_lines_into_one_chunk(monkeypatch):
    calls: list[list[str]] = []

    def _fake_chunk(chunk):
        calls.append([item["line_id"] for item in chunk])
        return {item["line_id"]: [(item["hanzi"], item["jyutping"], "")] for item in chunk}

    monkeypatch.setattr(llm, "_validate_segmentation_chunk", _fake_chunk)

    result = llm.validate_segmentation_batch(_flagged(5))

    # each "hanzi-N" fixture is ~8 chars, well under _CHUNK_CHAR_BUDGET —
    # all 5 pack into a single call
    assert calls == [["line-0", "line-1", "line-2", "line-3", "line-4"]]
    assert set(result.keys()) == {"line-0", "line-1", "line-2", "line-3", "line-4"}


def test_validate_segmentation_batch_one_chunk_failing_does_not_lose_the_others(monkeypatch):
    monkeypatch.setattr(llm, "_CHUNK_CHAR_BUDGET", 10)  # forces one line per chunk (each fixture item is 7 chars)

    def _fake_chunk(chunk):
        if chunk[0]["line_id"] == "line-2":
            raise RuntimeError("simulated truncated response")
        return {item["line_id"]: [(item["hanzi"], item["jyutping"], "")] for item in chunk}

    monkeypatch.setattr(llm, "_validate_segmentation_chunk", _fake_chunk)

    result = llm.validate_segmentation_batch(_flagged(5))

    # only line-2's own (single-item) chunk fails — everything else,
    # each in its own chunk too, is unaffected
    assert set(result.keys()) == {"line-0", "line-1", "line-3", "line-4"}
    assert "line-2" not in result


def test_validate_segmentation_batch_empty_input_makes_no_calls(monkeypatch):
    def _fail_if_called(chunk):
        raise AssertionError("should not be called for empty input")

    monkeypatch.setattr(llm, "_validate_segmentation_chunk", _fail_if_called)

    assert llm.validate_segmentation_batch([]) == {}


def test_validate_segmentation_batch_splits_and_reassembles_a_long_line(monkeypatch):
    """The actual regression this fix targets: one very long flagged line
    (over _LONG_LINE_SPLIT_THRESHOLD) must still come back as a single
    result under its original line_id, stitched together from however
    many LLM calls its pieces needed."""
    monkeypatch.setattr(llm, "_LONG_LINE_SPLIT_THRESHOLD", 20)
    monkeypatch.setattr(llm, "_CHUNK_CHAR_BUDGET", 20)

    long_hanzi = "係囉。" * 10  # 30 chars, well over the 20-char threshold
    long_jyutping = "Hai6 lo1." * 10
    flagged = [{"line_id": "line-huge", "hanzi": long_hanzi, "jyutping": long_jyutping}]

    def _fake_chunk(chunk):
        return {item["line_id"]: [(item["hanzi"], item["jyutping"], "")] for item in chunk}

    monkeypatch.setattr(llm, "_validate_segmentation_chunk", _fake_chunk)

    result = llm.validate_segmentation_batch(flagged)

    assert list(result.keys()) == ["line-huge"]
    # reassembled hanzi across all parts reproduces the original line exactly
    assert "".join(h for h, _, _ in result["line-huge"]) == long_hanzi


# --- define_word / pick_definition_sense — English-context threading and
# dictionary-grounded sense-picking, added alongside definitions.py's
# resolve_definition redesign. Mocks _get_client() with a fake client
# that records the prompt it was given, since these two functions use
# the plain messages.create() text-completion path, not messages.parse(). ---


class _FakeTextBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _FakeResponse:
    def __init__(self, text):
        self.content = [_FakeTextBlock(text)]


class _FakeMessages:
    def __init__(self, response_text):
        self.response_text = response_text
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return _FakeResponse(self.response_text)


class _FakeClient:
    def __init__(self, response_text):
        self.messages = _FakeMessages(response_text)


def test_define_word_includes_english_context_when_given(monkeypatch):
    fake_client = _FakeClient("to move")
    monkeypatch.setattr(llm, "_get_client", lambda: fake_client)

    result = llm.define_word(
        jyutping="dung6", hanzi="動", line_context="佢喺度郁緊", english_context="He is moving right now"
    )

    assert result == "to move"
    prompt = fake_client.messages.last_kwargs["messages"][0]["content"]
    assert "He is moving right now" in prompt
    assert "dung6" in prompt


def test_define_word_without_english_context_omits_it(monkeypatch):
    fake_client = _FakeClient("to move")
    monkeypatch.setattr(llm, "_get_client", lambda: fake_client)

    llm.define_word(jyutping="dung6", hanzi="動", line_context="佢喺度郁緊")

    prompt = fake_client.messages.last_kwargs["messages"][0]["content"]
    assert "translates to" not in prompt


def test_pick_definition_sense_includes_candidates_and_context(monkeypatch):
    fake_client = _FakeClient("right away; just")
    monkeypatch.setattr(llm, "_get_client", lambda: fake_client)

    result = llm.pick_definition_sense(
        jyutping="zau6",
        hanzi="就",
        candidates=["then; so", "right away; just"],
        line_context="佢就返嚟",
        english_context="He'll be back soon",
    )

    assert result == "right away; just"
    prompt = fake_client.messages.last_kwargs["messages"][0]["content"]
    assert "then; so" in prompt
    assert "right away; just" in prompt
    assert "He'll be back soon" in prompt
    assert "佢就返嚟" in prompt


def test_pick_definition_sense_without_english_context(monkeypatch):
    fake_client = _FakeClient("then; so")
    monkeypatch.setattr(llm, "_get_client", lambda: fake_client)

    llm.pick_definition_sense(
        jyutping="zau6", hanzi="就", candidates=["then; so", "right away; just"], line_context="佢就返嚟"
    )

    prompt = fake_client.messages.last_kwargs["messages"][0]["content"]
    assert "translates to" not in prompt
