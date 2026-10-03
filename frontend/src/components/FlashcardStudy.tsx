import { useState } from "react";
import type { WordToken } from "../types";

interface Props {
  words: WordToken[];
  onFinish: () => void;
  onClose: () => void;
}

interface Card {
  word: WordToken;
  misses: number;
}

function shuffled(words: WordToken[]): Card[] {
  const cards = words.map((word) => ({ word, misses: 0 }));
  for (let i = cards.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [cards[i], cards[j]] = [cards[j], cards[i]];
  }
  return cards;
}

// A card that's still missed on its 3rd try is dropped rather than
// requeued, to avoid a word the user genuinely doesn't know yet cycling
// forever in one sitting.
const MAX_MISSES = 3;

/** Per-dialogue flashcard drill over this dialogue's flagged words —
 * jyutping on the front, definition on the back. Deliberately
 * session-local: grading a card here never touches vocab_store's
 * known/learning/learned status (that's still only set from the Review
 * page itself) — the only durable trace of a session is the caller
 * bumping times_studied once the deck is fully cleared. */
export function FlashcardStudy({ words, onFinish, onClose }: Props) {
  const [queue, setQueue] = useState<Card[]>(() => shuffled(words));
  const [flipped, setFlipped] = useState(false);
  const [done, setDone] = useState(false);

  function handleGrade(knewIt: boolean) {
    const [current, ...rest] = queue;
    let next = rest;
    if (!knewIt) {
      const misses = current.misses + 1;
      if (misses < MAX_MISSES) next = [...rest, { word: current.word, misses }];
    }
    setQueue(next);
    setFlipped(false);
    if (next.length === 0) {
      setDone(true);
      onFinish();
    }
  }

  if (done) {
    return (
      <div className="flashcard-overlay">
        <div className="flashcard-modal">
          <p>Session complete — nice work!</p>
          <button className="flashcard-grade-button" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    );
  }

  const current = queue[0];

  return (
    <div className="flashcard-overlay">
      <div className="flashcard-modal">
        <div className="flashcard-header">
          <span>{queue.length} left</span>
          <button className="flashcard-close-button" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>
        <div className="flashcard-card" onClick={() => setFlipped((f) => !f)}>
          {flipped ? (
            <span className="flashcard-def">{current.word.definition || "(no definition)"}</span>
          ) : (
            <span className="flashcard-jyutping">{current.word.jyutping}</span>
          )}
        </div>
        {!flipped ? (
          <p className="flashcard-hint">Click the card to reveal the definition</p>
        ) : (
          <div className="flashcard-actions">
            <button className="flashcard-grade-button flashcard-unknown" onClick={() => handleGrade(false)}>
              Don't know
            </button>
            <button className="flashcard-grade-button flashcard-known" onClick={() => handleGrade(true)}>
              Know it
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
