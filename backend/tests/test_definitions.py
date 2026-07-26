"""Covers definitions.resolve_definition's branching — added when a
dictionary hit stopped being blindly collapsed to
hits[0]["definitions"][0] and became context-aware for genuinely
ambiguous words (multiple dictionary senses; also duplicate entries
across CC-Canto/CC-CEDICT, see flatten_candidate_definitions). Mocks at
the dictionary.lookup / llm function boundaries — resolve_definition
itself has no storage side effects (see dialogue_store.resolve_word_definition
for where a result actually gets cached, tested separately)."""

from app.models.vocab import DefinitionSource
from app.services import definitions


def _hit(definitions_list: list[str]) -> dict:
    return {"traditional": "X", "simplified": "X", "jyutping": "x1", "definitions": definitions_list}


def test_flatten_candidate_definitions_dedupes_across_hits():
    hits = [_hit(["a", "b"]), _hit(["b", "c"])]
    assert definitions.flatten_candidate_definitions(hits) == ["a", "b", "c"]


def test_flatten_candidate_definitions_empty_for_no_hits():
    assert definitions.flatten_candidate_definitions([]) == []


def test_resolve_definition_single_sense_skips_the_llm_entirely(monkeypatch):
    monkeypatch.setattr(definitions.dictionary, "lookup", lambda **kw: [_hit(["only sense"])])

    def _fail_if_called(*a, **kw):
        raise AssertionError("should not call the LLM for an unambiguous word")

    monkeypatch.setattr(definitions.llm, "pick_definition_sense", _fail_if_called)
    monkeypatch.setattr(definitions.llm, "define_word", _fail_if_called)

    result, source = definitions.resolve_definition(hanzi="X", jyutping="x1", line_context="...")
    assert result == "only sense"
    assert source == DefinitionSource.DICTIONARY


def test_resolve_definition_multiple_senses_calls_pick_definition_sense(monkeypatch):
    monkeypatch.setattr(definitions.dictionary, "lookup", lambda **kw: [_hit(["then", "right away"])])
    captured = {}

    def _fake_pick(**kwargs):
        captured.update(kwargs)
        return "right away"

    monkeypatch.setattr(definitions.llm, "pick_definition_sense", _fake_pick)

    result, source = definitions.resolve_definition(
        hanzi="就", jyutping="zau6", line_context="佢就返嚟", english_context="He'll be back soon"
    )

    assert result == "right away"
    assert source == DefinitionSource.LLM
    assert captured["candidates"] == ["then", "right away"]
    assert captured["english_context"] == "He'll be back soon"
    assert captured["line_context"] == "佢就返嚟"


def test_resolve_definition_falls_back_to_first_sense_if_llm_sense_picking_fails(monkeypatch):
    monkeypatch.setattr(definitions.dictionary, "lookup", lambda **kw: [_hit(["then", "right away"])])

    def _raise(**kwargs):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(definitions.llm, "pick_definition_sense", _raise)

    result, source = definitions.resolve_definition(hanzi="就", jyutping="zau6", line_context="...")
    assert result == "then"
    assert source == DefinitionSource.DICTIONARY


def test_resolve_definition_no_hits_falls_back_to_define_word(monkeypatch):
    monkeypatch.setattr(definitions.dictionary, "lookup", lambda **kw: [])
    captured = {}

    def _fake_define(**kwargs):
        captured.update(kwargs)
        return "a made-up word"

    monkeypatch.setattr(definitions.llm, "define_word", _fake_define)

    result, source = definitions.resolve_definition(
        hanzi=None, jyutping="xyz1", line_context="...", english_context="some translation"
    )
    assert result == "a made-up word"
    assert source == DefinitionSource.LLM
    assert captured["english_context"] == "some translation"


def test_resolve_definition_degrades_gracefully_when_everything_fails(monkeypatch):
    monkeypatch.setattr(definitions.dictionary, "lookup", lambda **kw: [])

    def _raise(**kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(definitions.llm, "define_word", _raise)

    result, source = definitions.resolve_definition(hanzi=None, jyutping="xyz1", line_context="...")
    assert "unavailable" in result
    assert source is None
