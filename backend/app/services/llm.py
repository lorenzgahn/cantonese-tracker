"""LLM call sites. Auth is via the user's claude.ai OAuth login
(`ant auth login`) per SPEC.md §9 — anthropic.Anthropic() picks up the
OAuth profile automatically with no code change; ANTHROPIC_API_KEY (if
ever set) is checked first by the SDK, so switching to metered billing
later needs no changes here either. Confirmed live (Phase 0.5): auth
succeeds, and the account needs API credits purchased separately at
console.anthropic.com — a claude.ai Pro/Max subscription does not cover
raw API calls, even authenticated via the same OAuth login.

define_word() is Step 3's per-word, on-click fallback (lazy — only ever
called for a word that's actually been flagged unknown).
generate_jyutping_batch() (Step 1a) and validate_segmentation_batch()
(Step 2) are the per-dialogue *batched* passes named in SPEC.md §4 —
one call per dialogue's flagged items, not one call per item, matching
the cost-efficiency design discussed for this app. Both use
client.messages.parse() with a Pydantic schema rather than free-text
parsing, since the result has to programmatically re-slot back into
specific words/lines by hanzi or line_id — a schema guarantees that
shape rather than hoping the model's prose matches a regex.
"""

import anthropic
from pydantic import BaseModel

from app.config import ANTHROPIC_MODEL

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def define_word(*, jyutping: str, hanzi: str | None, line_context: str) -> str:
    """Short, plain-English, learner-oriented gloss for a word the
    dictionary didn't have — matching the style the user already gets
    pasting into ChatGPT by hand (see SPEC.md §1)."""
    client = _get_client()
    word_desc = f'"{jyutping}"' + (f" ({hanzi})" if hanzi else "")
    prompt = (
        "You are helping a Cantonese learner. In the sentence:\n"
        f"{line_context}\n\n"
        f"Give a short, plain-English definition (5-10 words) for the word "
        f"{word_desc}. Reply with ONLY the definition text — no preamble, "
        "no quotes, no restating the word."
    )
    response = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=64,
        messages=[{"role": "user", "content": prompt}],
    )
    return next((b.text for b in response.content if b.type == "text"), "").strip()


class _GeneratedWord(BaseModel):
    hanzi: str
    jyutping: str


class _GeneratedWordBatch(BaseModel):
    words: list[_GeneratedWord]


def generate_jyutping_batch(hanzi_words: list[str]) -> dict[str, str]:
    """Step 1a's LLM fallback: jyutping for hanzi words the dictionary
    (whole-word and per-character) couldn't resolve at all — one call for
    every such word in a dialogue, not one call per word. Returns a
    hanzi -> jyutping map; words the model couldn't produce are simply
    absent from the result, so callers can tell a real miss from success."""
    if not hanzi_words:
        return {}
    client = _get_client()
    word_list = "\n".join(f"- {w}" for w in hanzi_words)
    prompt = (
        "You are helping build a Cantonese learning tool. For each of the "
        "following Cantonese (hanzi) words, give its Jyutping romanization "
        "(with tone numbers, no spaces within a word). These words were not "
        f"found in a dictionary lookup, so use your own knowledge:\n\n{word_list}"
    )
    response = client.messages.parse(
        model=ANTHROPIC_MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
        output_format=_GeneratedWordBatch,
    )
    return {w.hanzi: w.jyutping for w in response.parsed_output.words}


class _SegmentedWord(BaseModel):
    hanzi: str
    jyutping: str


class _SegmentedLine(BaseModel):
    line_id: str
    words: list[_SegmentedWord]


class _SegmentationBatch(BaseModel):
    lines: list[_SegmentedLine]


def validate_segmentation_batch(flagged_lines: list[dict]) -> dict[str, list[tuple[str, str]]]:
    """Step 2's LLM fallback: word-level (hanzi, jyutping) segmentation for
    lines the automatic aligner/segmenter couldn't handle (code-switched
    Latin-script spans, syllable-count mismatches, trie misses) — one call
    per dialogue covering every flagged line. Each item in flagged_lines
    needs "line_id", "hanzi", and "jyutping" (the line's original, unsegmented
    jyutping, used as a hint — may be empty for Type 4's synthesized case).
    Returns line_id -> ordered [(hanzi, jyutping), ...]; a line_id absent
    from the result means the model didn't return a segmentation for it."""
    if not flagged_lines:
        return {}
    client = _get_client()
    lines_desc = "\n".join(
        f'- line_id="{item["line_id"]}": hanzi="{item["hanzi"]}"'
        + (f', jyutping hint="{item["jyutping"]}"' if item.get("jyutping") else "")
        for item in flagged_lines
    )
    prompt = (
        "You are helping build a Cantonese learning tool. For each line below, "
        "split the hanzi into individual words (the smallest units a learner "
        "would look up) and give the Jyutping romanization for each word "
        "(with tone numbers, no spaces within a word). Preserve word order.\n\n"
        "Split fixed colloquial phrases into their component words too — do "
        "not keep a multi-word phrase as one token just because it's "
        "commonly said together as a set expression. For example:\n"
        "  - 好耐冇見 (\"long time no see\") must be split into 好耐 / 冇 / 見, "
        "not kept as one word.\n"
        "  - 着件雨褸 (\"put on a raincoat\") must be split into 着 / 件 / 雨褸, "
        "not kept as one word.\n"
        "Only keep multiple characters as a single word when they form one "
        "indivisible lexical item on their own, independent of surrounding "
        "context — e.g. 星期日 (\"Sunday\"), 獅子山 (\"Lion Rock\", a proper "
        "noun). As a rule of thumb, a word longer than 3 characters should "
        "be rare; if you're not confident a run of characters is a single "
        "dictionary entry on its own, split it further.\n\n"
        "Skip standalone punctuation marks (they are not words a learner would "
        "look up). Keep embedded English/Latin-script words as their own word "
        "entry, with the English word itself as its \"jyutping\" value. "
        "If a jyutping hint is given, use it to guide your romanization, but "
        "the hanzi word boundaries are what you need to determine:\n\n"
        f"{lines_desc}"
    )
    response = client.messages.parse(
        model=ANTHROPIC_MODEL,
        # Flagged lines here are whole speaker turns (this PDF's turn
        # reconstruction keeps a multi-sentence turn as one unit, and a
        # single embedded Latin-script word like "Instagram" flags the
        # entire turn) — confirmed live that 4096 truncates mid-JSON on a
        # 10-line batch and fails the whole call. 16000 clears that case;
        # revisit with per-line chunking if a transcript needs more.
        # Confirmed live that repeated calls on the same input can disagree
        # on whether to split a common fixed phrase (e.g. 好耐冇見) into its
        # component words or keep it as one token. temperature=0 would
        # normally help, but ANTHROPIC_MODEL (claude-opus-4-8) rejects it
        # ("temperature is deprecated for this model") — the explicit
        # splitting rule + worked examples in the prompt above is what's
        # actually carrying the fix here.
        max_tokens=16000,
        messages=[{"role": "user", "content": prompt}],
        output_format=_SegmentationBatch,
    )
    return {
        line.line_id: [(w.hanzi, w.jyutping) for w in line.words]
        for line in response.parsed_output.lines
    }
