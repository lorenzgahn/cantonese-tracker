"""Step 3 orchestration: resolve a definition for a word that's just been
flagged unknown — dictionary first, LLM fallback for misses/contextual
sense. Called at most once per word (the caller only invokes this when
the vocab store doesn't already have a cached definition) — see
SPEC.md §4 Step 3.
"""

import logging

from app.models.vocab import DefinitionSource
from app.services import dictionary, llm

logger = logging.getLogger(__name__)


def resolve_definition(
    *, hanzi: str | None, jyutping: str, line_context: str
) -> tuple[str, DefinitionSource | None]:
    hits = dictionary.lookup(hanzi=hanzi, jyutping=jyutping)
    if hits:
        # v1 takes the first sense rather than disambiguating — an open
        # question in SPEC.md §10, not a bug.
        return hits[0]["definitions"][0], DefinitionSource.DICTIONARY

    try:
        text = llm.define_word(jyutping=jyutping, hanzi=hanzi, line_context=line_context)
        return text, DefinitionSource.LLM
    except Exception as e:
        # Degrade gracefully rather than 500ing the click endpoint — most
        # likely cause right now is that `ant auth login` hasn't been run
        # yet (see Phase 0.5). The placeholder makes that visible in the
        # UI instead of silently caching a wrong/empty definition.
        logger.warning("LLM definition fallback failed for %r: %s", jyutping, e)
        return f"(definition unavailable — {e.__class__.__name__}: {e})", None
