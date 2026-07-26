"""Covers the storage-layer functions added for Phase 10's Vocab
Dashboard and Dialogue Library screens: vocab_store.promote/delete and
dialogue_store.list_dialogues. HTTP wiring itself (the actual endpoints
in routers/vocab.py and routers/review.py) was verified live via curl
against the real running server, matching this project's established
pattern of service-layer pytest coverage + manual HTTP/browser
verification for the wiring."""

from pathlib import Path

import pytest

from app.models.dialogue import StoredDialogue, StoredLine, StoredWordToken
from app.models.vocab import DefinitionSource, VocabEntry, VocabStatus
from app.services import dialogue_store, vocab_store
from app.services.segmentation import compute_word_id


@pytest.fixture(autouse=True)
def isolated_dialogues_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(dialogue_store, "DIALOGUES_DIR", tmp_path)


def test_promote_moves_learning_to_learned():
    vocab_store.save(VocabEntry(id="w1", status=VocabStatus.LEARNING))
    entry = vocab_store.promote("w1")
    assert entry.status == VocabStatus.LEARNED
    assert vocab_store.get("w1").status == VocabStatus.LEARNED


def test_promote_raises_for_unknown_word():
    with pytest.raises(ValueError):
        vocab_store.promote("does-not-exist")


def test_delete_removes_an_entry():
    vocab_store.save(VocabEntry(id="w2", status=VocabStatus.KNOWN))
    assert vocab_store.get("w2") is not None
    vocab_store.delete("w2")
    assert vocab_store.get("w2") is None


def test_delete_is_a_no_op_for_a_missing_word():
    vocab_store.delete("never-existed")  # must not raise


def _dialogue(dialogue_id: str, title: str) -> StoredDialogue:
    return StoredDialogue(
        id=dialogue_id,
        title=title,
        lines=[StoredLine(id="l1", words=[StoredWordToken(token_id="l1-w0", word_id="w1", jyutping="a1")])],
        source_type="plain_jyutping",
        imported_at="2026-07-10",
    )


def test_list_dialogues_returns_all_stored_dialogues():
    dialogue_store.save_stored(_dialogue("d1", "First"))
    dialogue_store.save_stored(_dialogue("d2", "Second"))

    dialogues = dialogue_store.list_dialogues()
    assert {d.id for d in dialogues} == {"d1", "d2"}
    assert {d.title for d in dialogues} == {"First", "Second"}


def test_list_dialogues_empty_when_none_stored():
    assert dialogue_store.list_dialogues() == []


def test_list_dialogues_preserves_source_type_and_imported_at():
    dialogue_store.save_stored(_dialogue("d1", "First"))
    [dialogue] = dialogue_store.list_dialogues()
    assert dialogue.source_type == "plain_jyutping"
    assert dialogue.imported_at == "2026-07-10"


def test_delete_stored_removes_a_dialogue():
    dialogue_store.save_stored(_dialogue("d1", "First"))
    assert dialogue_store.load_stored("d1") is not None
    dialogue_store.delete_stored("d1")
    assert dialogue_store.load_stored("d1") is None


def test_delete_stored_is_a_no_op_for_a_missing_dialogue():
    dialogue_store.delete_stored("never-existed")  # must not raise


def _mergeable_dialogue() -> StoredDialogue:
    return StoredDialogue(
        id="d1",
        title="Test",
        lines=[
            StoredLine(
                id="l1",
                words=[
                    StoredWordToken(token_id="l1-w0", word_id="li1", jyutping="li1", hanzi="呢"),
                    StoredWordToken(token_id="l1-w1", word_id="paai4", jyutping="paai4", hanzi="排"),
                    StoredWordToken(token_id="l1-w2", word_id="dou1", jyutping="dou1", hanzi="都"),
                ],
            )
        ],
    )


def test_merge_adjacent_tokens_combines_hanzi_and_jyutping():
    dialogue_store.save_stored(_mergeable_dialogue())
    stored, merged_word_id = dialogue_store.merge_adjacent_tokens("d1", "l1", "li1")

    assert merged_word_id == compute_word_id("li1 paai4", "呢排")
    line = stored.lines[0]
    assert [w.word_id for w in line.words] == [compute_word_id("li1 paai4", "呢排"), "dou1"]
    assert line.words[0].hanzi == "呢排"
    assert line.words[0].jyutping == "li1 paai4"


def test_merge_adjacent_tokens_persists_to_disk():
    dialogue_store.save_stored(_mergeable_dialogue())
    dialogue_store.merge_adjacent_tokens("d1", "l1", "li1")

    reloaded = dialogue_store.load_stored("d1")
    assert [w.word_id for w in reloaded.lines[0].words] == [compute_word_id("li1 paai4", "呢排"), "dou1"]


def test_merge_adjacent_tokens_raises_for_last_word_in_line():
    dialogue_store.save_stored(_mergeable_dialogue())
    with pytest.raises(ValueError):
        dialogue_store.merge_adjacent_tokens("d1", "l1", "dou1")


def test_merge_adjacent_tokens_raises_for_unknown_word():
    dialogue_store.save_stored(_mergeable_dialogue())
    with pytest.raises(ValueError):
        dialogue_store.merge_adjacent_tokens("d1", "l1", "never-seen")


def test_merge_adjacent_tokens_raises_for_unknown_dialogue():
    with pytest.raises(ValueError):
        dialogue_store.merge_adjacent_tokens("never-seen", "l1", "li1")


def _splittable_dialogue() -> StoredDialogue:
    return StoredDialogue(
        id="d1",
        title="Test",
        lines=[
            StoredLine(
                id="l1",
                words=[
                    StoredWordToken(
                        token_id="l1-w0", word_id="li1paai4dou1", jyutping="li1 paai4 dou1", hanzi="呢排都"
                    ),
                    StoredWordToken(token_id="l1-w1", word_id="hai6", jyutping="hai6", hanzi="係"),
                ],
            )
        ],
    )


def test_split_token_explodes_into_one_token_per_syllable():
    dialogue_store.save_stored(_splittable_dialogue())
    stored, new_tokens = dialogue_store.split_token("d1", "l1", "li1paai4dou1")

    expected = [compute_word_id("li1", "呢"), compute_word_id("paai4", "排"), compute_word_id("dou1", "都")]
    assert [t.word_id for t in new_tokens] == expected
    line = stored.lines[0]
    assert [w.word_id for w in line.words] == [*expected, "hai6"]


def test_split_token_distributes_hanzi_one_char_per_syllable():
    dialogue_store.save_stored(_splittable_dialogue())
    _, new_tokens = dialogue_store.split_token("d1", "l1", "li1paai4dou1")
    assert [t.hanzi for t in new_tokens] == ["呢", "排", "都"]


def test_split_token_leaves_hanzi_unset_when_counts_mismatch():
    dialogue = StoredDialogue(
        id="d1",
        title="Test",
        lines=[
            StoredLine(
                id="l1",
                words=[StoredWordToken(token_id="l1-w0", word_id="x", jyutping="haang4 KEEP", hanzi="行")],
            )
        ],
    )
    dialogue_store.save_stored(dialogue)
    _, new_tokens = dialogue_store.split_token("d1", "l1", "x")
    assert [t.hanzi for t in new_tokens] == [None, None]


def test_split_token_persists_to_disk():
    dialogue_store.save_stored(_splittable_dialogue())
    dialogue_store.split_token("d1", "l1", "li1paai4dou1")

    reloaded = dialogue_store.load_stored("d1")
    expected = [compute_word_id("li1", "呢"), compute_word_id("paai4", "排"), compute_word_id("dou1", "都"), "hai6"]
    assert [w.word_id for w in reloaded.lines[0].words] == expected


def test_split_token_raises_for_single_syllable_word():
    dialogue_store.save_stored(_splittable_dialogue())
    with pytest.raises(ValueError):
        dialogue_store.split_token("d1", "l1", "hai6")


def test_split_token_raises_for_unknown_word():
    dialogue_store.save_stored(_splittable_dialogue())
    with pytest.raises(ValueError):
        dialogue_store.split_token("d1", "l1", "never-seen")


def test_split_and_merge_round_trip_recovers_original_grouping():
    """The documented workflow: split a bad merge all the way down, then
    manually re-merge the correct adjacent pair back together."""
    dialogue_store.save_stored(_splittable_dialogue())
    dialogue_store.split_token("d1", "l1", "li1paai4dou1")

    stored, merged_word_id = dialogue_store.merge_adjacent_tokens("d1", "l1", compute_word_id("li1", "呢"))
    assert merged_word_id == compute_word_id("li1 paai4", "呢排")
    assert [w.word_id for w in stored.lines[0].words] == [
        compute_word_id("li1 paai4", "呢排"),
        compute_word_id("dou1", "都"),
        "hai6",
    ]


def _editable_dialogue() -> StoredDialogue:
    return StoredDialogue(
        id="d1",
        title="Test",
        lines=[
            StoredLine(
                id="l1",
                words=[
                    StoredWordToken(token_id="l1-w0", word_id="dung6", jyutping="dung6", hanzi="動"),
                    StoredWordToken(token_id="l1-w1", word_id="hai6", jyutping="hai6", hanzi="係"),
                ],
            )
        ],
    )


def test_edit_token_jyutping_recomputes_word_id():
    dialogue_store.save_stored(_editable_dialogue())
    stored, corrected = dialogue_store.edit_token_jyutping("d1", "l1", "dung6", "tung4")

    assert corrected.word_id == "tung4"
    assert corrected.jyutping == "tung4"
    assert corrected.hanzi is None  # cleared — the old hanzi belonged to the wrong reading
    assert [w.word_id for w in stored.lines[0].words] == ["tung4", "hai6"]


def test_edit_token_jyutping_persists_to_disk():
    dialogue_store.save_stored(_editable_dialogue())
    dialogue_store.edit_token_jyutping("d1", "l1", "dung6", "tung4")

    reloaded = dialogue_store.load_stored("d1")
    assert reloaded.lines[0].words[0].word_id == "tung4"


def test_edit_token_jyutping_keeps_the_same_token_id():
    dialogue_store.save_stored(_editable_dialogue())
    _, corrected = dialogue_store.edit_token_jyutping("d1", "l1", "dung6", "tung4")
    assert corrected.token_id == "l1-w0"


def test_edit_token_jyutping_raises_for_empty_replacement():
    dialogue_store.save_stored(_editable_dialogue())
    with pytest.raises(ValueError):
        dialogue_store.edit_token_jyutping("d1", "l1", "dung6", "   ")


def test_edit_token_jyutping_raises_for_unknown_word():
    dialogue_store.save_stored(_editable_dialogue())
    with pytest.raises(ValueError):
        dialogue_store.edit_token_jyutping("d1", "l1", "never-seen", "tung4")


def _dialogue_with_shared_word() -> StoredDialogue:
    """Two dialogues (same fixture shape reused for both) sharing a word
    whose jyutping means different things in each — the scenario
    definition_overrides exists for."""
    return StoredDialogue(
        id="d1",
        title="Test",
        lines=[
            StoredLine(
                id="l1",
                words=[StoredWordToken(token_id="l1-w0", word_id="zung6", jyutping="zung6", hanzi="仲")],
            )
        ],
    )


def test_set_definition_override_persists_to_disk():
    dialogue_store.save_stored(_dialogue_with_shared_word())
    dialogue_store.set_definition_override("d1", "zung6", "still; yet")

    reloaded = dialogue_store.load_stored("d1")
    assert reloaded.definition_overrides == {"zung6": "still; yet"}


def test_set_definition_override_raises_for_unknown_dialogue():
    with pytest.raises(ValueError):
        dialogue_store.set_definition_override("never-seen", "zung6", "still; yet")


def test_join_with_vocab_prefers_override_over_global_default():
    vocab_store.save(
        VocabEntry(
            id="zung6",
            status=VocabStatus.LEARNING,
            definition="(adverb) even more so",
            source_of_definition=DefinitionSource.DICTIONARY,
        )
    )
    stored = _dialogue_with_shared_word()
    dialogue_store.save_stored(stored)
    dialogue_store.set_definition_override("d1", "zung6", "still; yet")

    joined = dialogue_store.get_dialogue("d1")
    token = joined.lines[0].words[0]
    assert token.definition == "still; yet"
    assert token.source_of_definition == DefinitionSource.MANUAL
    # status stays global — untouched by the per-dialogue override
    assert token.status == VocabStatus.LEARNING


def test_join_with_vocab_falls_back_to_global_default_without_an_override():
    vocab_store.save(
        VocabEntry(
            id="zung6",
            status=VocabStatus.LEARNING,
            definition="(adverb) even more so",
            source_of_definition=DefinitionSource.DICTIONARY,
        )
    )
    dialogue_store.save_stored(_dialogue_with_shared_word())

    joined = dialogue_store.get_dialogue("d1")
    token = joined.lines[0].words[0]
    assert token.definition == "(adverb) even more so"
    assert token.source_of_definition == DefinitionSource.DICTIONARY


def test_override_in_one_dialogue_does_not_affect_another():
    vocab_store.save(VocabEntry(id="zung6", status=VocabStatus.LEARNING, definition="(adverb) even more so"))
    dialogue_store.save_stored(_dialogue_with_shared_word())
    other = _dialogue_with_shared_word()
    other.id = "d2"
    dialogue_store.save_stored(other)

    dialogue_store.set_definition_override("d1", "zung6", "still; yet")

    assert dialogue_store.get_dialogue("d1").lines[0].words[0].definition == "still; yet"
    assert dialogue_store.get_dialogue("d2").lines[0].words[0].definition == "(adverb) even more so"


def test_set_link_url_persists_to_disk():
    dialogue_store.save_stored(_dialogue_with_shared_word())
    dialogue_store.set_link_url("d1", "https://example.com/episode-1")

    reloaded = dialogue_store.load_stored("d1")
    assert reloaded.link_url == "https://example.com/episode-1"


def test_set_link_url_clears_with_empty_string():
    dialogue_store.save_stored(_dialogue_with_shared_word())
    dialogue_store.set_link_url("d1", "https://example.com/episode-1")
    dialogue_store.set_link_url("d1", "")

    reloaded = dialogue_store.load_stored("d1")
    assert reloaded.link_url is None


def test_set_link_url_raises_for_unknown_dialogue():
    with pytest.raises(ValueError):
        dialogue_store.set_link_url("never-seen", "https://example.com/episode-1")


def test_join_with_vocab_carries_link_url_through():
    stored = _dialogue_with_shared_word()
    stored.link_url = "https://example.com/episode-1"
    dialogue_store.save_stored(stored)

    joined = dialogue_store.get_dialogue("d1")
    assert joined.link_url == "https://example.com/episode-1"


# --- resolve_word_definition: where an ambiguous-vs-unambiguous word's
# definition gets cached (global default vs this dialogue's override) ---


def _single_sense_hit():
    return [{"traditional": "仲", "simplified": "仲", "jyutping": "zung6", "definitions": ["only sense"]}]


def _multi_sense_hit():
    return [
        {
            "traditional": "仲",
            "simplified": "仲",
            "jyutping": "zung6",
            "definitions": ["still; yet", "even more so"],
        }
    ]


def test_resolve_word_definition_reuses_the_global_cache_for_an_unambiguous_word(monkeypatch):
    monkeypatch.setattr(dialogue_store.dictionary, "lookup", lambda **kw: _single_sense_hit())
    dialogue_store.save_stored(_dialogue_with_shared_word())
    vocab_store.save(
        VocabEntry(
            id="zung6", status=VocabStatus.LEARNING, definition="cached def", source_of_definition=DefinitionSource.DICTIONARY
        )
    )

    def _fail_if_called(**kwargs):
        raise AssertionError("should reuse the global cache, not resolve again")

    monkeypatch.setattr(dialogue_store.definitions, "resolve_definition", _fail_if_called)

    definition, source = dialogue_store.resolve_word_definition(
        "d1", "zung6", hanzi="仲", jyutping="zung6", line_context="...", english_context=None
    )
    assert definition == "cached def"
    assert source == DefinitionSource.DICTIONARY


def test_resolve_word_definition_resolves_and_caches_globally_when_unambiguous_and_uncached(monkeypatch):
    monkeypatch.setattr(dialogue_store.dictionary, "lookup", lambda **kw: _single_sense_hit())
    dialogue_store.save_stored(_dialogue_with_shared_word())
    monkeypatch.setattr(
        dialogue_store.definitions, "resolve_definition", lambda **kw: ("fresh def", DefinitionSource.DICTIONARY)
    )

    definition, source = dialogue_store.resolve_word_definition(
        "d1", "zung6", hanzi="仲", jyutping="zung6", line_context="...", english_context=None
    )
    assert definition == "fresh def"
    # unambiguous — must not create a per-dialogue override
    reloaded = dialogue_store.load_stored("d1")
    assert "zung6" not in reloaded.definition_overrides


def test_resolve_word_definition_always_resolves_fresh_for_an_ambiguous_word(monkeypatch):
    monkeypatch.setattr(dialogue_store.dictionary, "lookup", lambda **kw: _multi_sense_hit())
    dialogue_store.save_stored(_dialogue_with_shared_word())
    # a different dialogue already cached *a* definition globally
    vocab_store.save(
        VocabEntry(
            id="zung6",
            status=VocabStatus.LEARNING,
            definition="some other dialogue's sense",
            source_of_definition=DefinitionSource.MANUAL,
        )
    )
    monkeypatch.setattr(
        dialogue_store.definitions, "resolve_definition", lambda **kw: ("this dialogue's sense", DefinitionSource.LLM)
    )

    definition, source = dialogue_store.resolve_word_definition(
        "d1", "zung6", hanzi="仲", jyutping="zung6", line_context="...", english_context=None
    )
    assert definition == "this dialogue's sense"
    # stamped MANUAL — matches what join_with_vocab will show on every
    # later read of this override, so the click response and a reload
    # never disagree
    assert source == DefinitionSource.MANUAL

    reloaded = dialogue_store.load_stored("d1")
    assert reloaded.definition_overrides["zung6"] == "this dialogue's sense"


def test_resolve_word_definition_is_idempotent_within_a_dialogue(monkeypatch):
    dialogue_store.save_stored(_dialogue_with_shared_word())
    dialogue_store.set_definition_override("d1", "zung6", "already resolved")

    def _fail_if_called(**kwargs):
        raise AssertionError("an override already exists for this dialogue — must not resolve again")

    monkeypatch.setattr(dialogue_store.dictionary, "lookup", _fail_if_called)
    monkeypatch.setattr(dialogue_store.definitions, "resolve_definition", _fail_if_called)

    definition, source = dialogue_store.resolve_word_definition(
        "d1", "zung6", hanzi="仲", jyutping="zung6", line_context="...", english_context=None
    )
    assert definition == "already resolved"
    assert source == DefinitionSource.MANUAL


def test_resolve_word_definition_raises_for_unknown_dialogue():
    with pytest.raises(ValueError):
        dialogue_store.resolve_word_definition(
            "never-seen", "zung6", hanzi=None, jyutping="zung6", line_context="", english_context=None
        )
