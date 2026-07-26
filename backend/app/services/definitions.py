"""Step 3 orchestration: resolve a definition for a word that's just been
flagged unknown — dictionary first, LLM fallback for misses/contextual
sense. Called at most once per (dialogue, word) — the caller only
invokes this when it doesn't already have a cached result for this
occurrence (see dialogue_store.resolve_word_definition, which owns the
"where does the result get cached" decision; this module stays a pure
"given these inputs, produce the best definition" function with no
storage side effects) — see SPEC.md §4 Step 3.
"""

import logging

from app.models.vocab import DefinitionSource
from app.services import dictionary, llm

logger = logging.getLogger(__name__)


def flatten_candidate_definitions(hits: list[dictionary.DictRecord]) -> list[str]:
    """Every dictionary sense across every hit, in order, deduped. A
    hanzi+jyutping lookup can return more than one hit — CC-Canto and
    CC-CEDICT-readings are two merged sources, and genuine
    duplicate/near-duplicate entries for the same word do exist — and a
    single hit can itself list more than one sense. Both used to
    silently collapse to hits[0]["definitions"][0]; this is what feeds
    resolve_definition's ambiguity check instead."""
    seen: set[str] = set()
    candidates: list[str] = []
    for hit in hits:
        for d in hit["definitions"]:
            if d not in seen:
                seen.add(d)
                candidates.append(d)
    return candidates


def resolve_definition(
    *, hanzi: str | None, jyutping: str, line_context: str, english_context: str | None = None
) -> tuple[str, DefinitionSource | None]:
    """Returns (definition, source). Three cases:
      - Exactly one dictionary sense across all hits: use it directly,
        no LLM call — the common case, stays as fast/free as before.
      - More than one: genuinely ambiguous, ask the LLM to pick the
        sense that fits this occurrence, grounded in the real
        candidates (not free-generated) and whatever context is
        available (english_context when present, line_context always).
      - No dictionary hits at all: existing LLM-from-scratch fallback,
        now also given english_context when available.
    Degrades gracefully on any LLM failure rather than raising, matching
    every other LLM call site in this app — falls back to the first
    dictionary candidate if there was at least one, or a visible
    placeholder if there wasn't."""
    hits = dictionary.lookup(hanzi=hanzi, jyutping=jyutping)
    candidates = flatten_candidate_definitions(hits)

    if len(candidates) == 1:
        return candidates[0], DefinitionSource.DICTIONARY

    if candidates:
        try:
            text = llm.pick_definition_sense(
                jyutping=jyutping,
                hanzi=hanzi,
                candidates=candidates,
                line_context=line_context,
                english_context=english_context,
            )
            return text, DefinitionSource.LLM
        except Exception as e:
            logger.warning("LLM sense-picking failed for %r, falling back to first dictionary sense: %s", jyutping, e)
            return candidates[0], DefinitionSource.DICTIONARY

    try:
        text = llm.define_word(jyutping=jyutping, hanzi=hanzi, line_context=line_context, english_context=english_context)
        return text, DefinitionSource.LLM
    except Exception as e:
        # Degrade gracefully rather than 500ing the click endpoint — most
        # likely cause right now is that `ant auth login` hasn't been run
        # yet (see Phase 0.5). The placeholder makes that visible in the
        # UI instead of silently caching a wrong/empty definition.
        logger.warning("LLM definition fallback failed for %r: %s", jyutping, e)
        return f"(definition unavailable — {e.__class__.__name__}: {e})", None
