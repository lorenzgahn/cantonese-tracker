"""Type 2 importer: plain pasted jyutping text, no hanzi, no brackets, no
speaker structure — the weakest-signal input type (SPEC.md §3/§8): no
hanzi to disambiguate homophones or seed segmentation, so this is the
importer most reliant on the LLM validation pass.

Each non-empty line becomes one Line (speaker=None), segmented via the
same jyutping-trie longest-match as Type 3's non-bracketed spans (Step 2,
Type 2 path). A segmented word with no CC-Canto entry is flagged
word-level for the LLM pass, mirroring Type 4's confidence tiering —
except there's no per-character fallback tier here, since a jyutping
syllable (unlike a hanzi character) has no smaller decomposable unit to
fall back to.
"""

from dataclasses import dataclass, field
from datetime import date

from app.models.dialogue import StoredDialogue, StoredLine, StoredWordToken
from app.services import dictionary
from app.services.segmentation import compute_word_id, segment_jyutping_trie


@dataclass
class ImportResult:
    dialogue: StoredDialogue
    # Word-level, {"line_id", "jyutping", "reason": "no_dictionary_match"}
    # — every flagged item here is this one reason, since there's no
    # per-character-style fallback tier for jyutping the way there is
    # for hanzi (Type 4).
    flagged_words: list[dict] = field(default_factory=list)


def build_stored_dialogue(dialogue_id: str, title: str, raw_text: str) -> ImportResult:
    raw_lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    lines: list[StoredLine] = []
    flagged: list[dict] = []

    for i, raw_line in enumerate(raw_lines):
        line_id = f"line-{i}"
        words = segment_jyutping_trie(raw_line)
        tokens: list[StoredWordToken] = []

        for j, word in enumerate(words):
            if not dictionary.lookup(jyutping=word):
                flagged.append({"line_id": line_id, "jyutping": word, "reason": "no_dictionary_match"})

            tokens.append(
                StoredWordToken(
                    token_id=f"{line_id}-w{j}",
                    word_id=compute_word_id(word, None),
                    jyutping=word,
                    hanzi=None,
                )
            )

        lines.append(StoredLine(id=line_id, speaker=None, words=tokens))

    dialogue = StoredDialogue(
        id=dialogue_id,
        title=title,
        lines=lines,
        source_type="plain_jyutping",
        imported_at=date.today().isoformat(),
    )
    return ImportResult(dialogue=dialogue, flagged_words=flagged)


def import_plain_jyutping(raw_text: str, dialogue_id: str, title: str) -> ImportResult:
    return build_stored_dialogue(dialogue_id, title, raw_text)
