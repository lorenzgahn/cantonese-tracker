"""Covers every arrow in SPEC.md §5's status diagram:

    new (not yet in store)
      └─ on first review, unclicked → known
      └─ on first review, clicked   → learning
    learning ──(manually promoted)──> learned
    known / learning / learned ──(clicked again in a later dialogue)──> learning
"""

import pytest

from app.models.dialogue import StoredDialogue, StoredLine, StoredWordToken
from app.models.vocab import DefinitionSource, VocabStatus
from app.services import vocab_store


# --- pure transition function: on_click ---
# Clicking always flags a word as learning, regardless of any prior state.


@pytest.mark.parametrize(
    "prior_status",
    [None, VocabStatus.KNOWN, VocabStatus.LEARNING, VocabStatus.LEARNED],
)
def test_on_click_always_learning(prior_status):
    current = None
    if prior_status is not None:
        current = vocab_store.VocabEntry(id="w", status=prior_status)
    assert vocab_store.on_click(current) == VocabStatus.LEARNING


# --- pure transition function: on_unclicked_at_finish_review ---


def test_on_unclicked_new_word_becomes_known():
    assert vocab_store.on_unclicked_at_finish_review(None) == VocabStatus.KNOWN


@pytest.mark.parametrize(
    "prior_status", [VocabStatus.KNOWN, VocabStatus.LEARNING, VocabStatus.LEARNED]
)
def test_on_unclicked_existing_word_unchanged(prior_status):
    current = vocab_store.VocabEntry(id="w", status=prior_status)
    assert vocab_store.on_unclicked_at_finish_review(current) == prior_status


# --- pure transition function: promote_to_learned ---


def test_promote_learning_to_learned():
    current = vocab_store.VocabEntry(id="w", status=VocabStatus.LEARNING)
    assert vocab_store.promote_to_learned(current) == VocabStatus.LEARNED


# --- integration: record_click persists on_click's result ---


def test_record_click_creates_new_word_as_learning():
    entry = vocab_store.record_click(
        "faan1zo2", dialogue_id="d1", line_id="l1", hanzi="返咗", jyutping="faan1 zo2"
    )
    assert entry.status == VocabStatus.LEARNING
    assert entry.times_seen == 1
    assert vocab_store.get("faan1zo2").status == VocabStatus.LEARNING


def test_record_click_flips_known_word_to_learning_across_dialogues():
    """The spec's central cross-dialogue case: a word marked known while
    reviewing dialogue A, then clicked while reviewing dialogue B, must
    flip to learning globally — not just within dialogue B."""
    vocab_store.save(vocab_store.VocabEntry(id="haang4saan1", status=VocabStatus.KNOWN))

    entry = vocab_store.record_click(
        "haang4saan1", dialogue_id="d2", line_id="l1", hanzi="行山", jyutping="haang4 saan1"
    )

    assert entry.status == VocabStatus.LEARNING
    assert vocab_store.get("haang4saan1").status == VocabStatus.LEARNING


def test_record_click_reinforces_already_learning_word():
    vocab_store.save(vocab_store.VocabEntry(id="lo1", status=VocabStatus.LEARNING, times_seen=1))
    entry = vocab_store.record_click("lo1", dialogue_id="d2", line_id="l1", hanzi="囉", jyutping="lo1")
    assert entry.status == VocabStatus.LEARNING
    assert entry.times_seen == 2


# --- pure transition function: on_unclick ---


def test_on_unclick_always_known():
    current = vocab_store.VocabEntry(id="w", status=VocabStatus.LEARNING)
    assert vocab_store.on_unclick(current) == VocabStatus.KNOWN


# --- integration: unclick reverses a flagged word back to known ---


def test_unclick_flips_learning_word_to_known():
    vocab_store.save(vocab_store.VocabEntry(id="lo1", status=VocabStatus.LEARNING, times_seen=2))
    entry = vocab_store.unclick("lo1")
    assert entry.status == VocabStatus.KNOWN
    assert vocab_store.get("lo1").status == VocabStatus.KNOWN


def test_unclick_preserves_definition_and_times_seen():
    vocab_store.save(
        vocab_store.VocabEntry(
            id="lo1", status=VocabStatus.LEARNING, definition="a sentence-final particle", times_seen=3
        )
    )
    entry = vocab_store.unclick("lo1")
    assert entry.definition == "a sentence-final particle"
    assert entry.times_seen == 3


def test_unclick_missing_word_raises():
    with pytest.raises(ValueError):
        vocab_store.unclick("never_seen")


# --- integration: update_definition overwrites a cached definition ---


def test_update_definition_overwrites_a_wrong_definition():
    vocab_store.save(
        vocab_store.VocabEntry(
            id="li1", status=VocabStatus.LEARNING, definition="wrong guess", source_of_definition=None
        )
    )
    entry = vocab_store.update_definition(
        "li1", definition="correct definition", source_of_definition=DefinitionSource.DICTIONARY
    )
    assert entry.definition == "correct definition"
    assert entry.source_of_definition == DefinitionSource.DICTIONARY
    assert vocab_store.get("li1").definition == "correct definition"


def test_update_definition_does_not_touch_status_or_times_seen():
    vocab_store.save(vocab_store.VocabEntry(id="li1", status=VocabStatus.LEARNING, times_seen=5))
    entry = vocab_store.update_definition("li1", definition="x", source_of_definition=None)
    assert entry.status == VocabStatus.LEARNING
    assert entry.times_seen == 5


def test_update_definition_missing_word_raises():
    with pytest.raises(ValueError):
        vocab_store.update_definition("never_seen", definition="x", source_of_definition=None)


# --- integration: finish_review commits the unclicked words ---


def _dialogue() -> StoredDialogue:
    return StoredDialogue(
        id="d1",
        title="Test",
        lines=[
            StoredLine(
                id="l1",
                speaker=None,
                words=[
                    StoredWordToken(token_id="l1-w0", word_id="new_word", jyutping="a1", hanzi="甲"),
                    StoredWordToken(token_id="l1-w1", word_id="clicked_word", jyutping="b1", hanzi="乙"),
                    StoredWordToken(token_id="l1-w2", word_id="existing_learning", jyutping="c1", hanzi="丙"),
                ],
            )
        ],
    )


def test_finish_review_commits_unclicked_new_word_as_known():
    vocab_store.finish_review(_dialogue(), clicked_word_ids=set())
    assert vocab_store.get("new_word").status == VocabStatus.KNOWN


def test_finish_review_does_not_touch_clicked_words():
    # Simulate: the word was clicked during review (record_click already
    # ran and set it to learning) before Finish Review is hit.
    vocab_store.record_click("clicked_word", dialogue_id="d1", line_id="l1", hanzi="乙", jyutping="b1")
    vocab_store.finish_review(_dialogue(), clicked_word_ids={"clicked_word"})
    assert vocab_store.get("clicked_word").status == VocabStatus.LEARNING


def test_finish_review_leaves_existing_status_unchanged_when_not_clicked():
    """Not clicking a word this time must not downgrade an
    already-learning word back to known."""
    vocab_store.save(vocab_store.VocabEntry(id="existing_learning", status=VocabStatus.LEARNING))
    vocab_store.finish_review(_dialogue(), clicked_word_ids=set())
    assert vocab_store.get("existing_learning").status == VocabStatus.LEARNING


def test_reopening_a_dialogue_does_not_reset_status():
    """Re-visiting an already-reviewed dialogue must not reset a
    previously committed status just by being loaded again — finish_review
    is idempotent for words that already have an entry."""
    vocab_store.finish_review(_dialogue(), clicked_word_ids=set())
    assert vocab_store.get("new_word").status == VocabStatus.KNOWN

    vocab_store.record_click("new_word", dialogue_id="d2", line_id="l1", hanzi="甲", jyutping="a1")
    assert vocab_store.get("new_word").status == VocabStatus.LEARNING

    # Re-opening d1 and hitting finish-review again without clicking it
    # must leave it as learning, not reset it back to known.
    vocab_store.finish_review(_dialogue(), clicked_word_ids=set())
    assert vocab_store.get("new_word").status == VocabStatus.LEARNING
