import { useEffect, useState } from "react";
import { hasCantoneseVoice, onVoicesChanged, speakCantonese } from "../speech";
import type { WordToken } from "../types";

interface Props {
  words: WordToken[];
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

/** Flashcard drill over one checkpoint's chunk of flagged words (see
 * ReviewPage) — jyutping on the front, definition on the back, spoken
 * aloud in Cantonese when the card appears. Deliberately session-local:
 * grading a card here never touches vocab_store's known/learning/learned
 * status (that's still only set from the Review page itself). */
export function FlashcardStudy({ words, onClose }: Props) {
  const [queue, setQueue] = useState<Card[]>(() => shuffled(words));
  const [flipped, setFlipped] = useState(false);
  const [voiceReady, setVoiceReady] = useState(hasCantoneseVoice);

  useEffect(() => onVoicesChanged(() => setVoiceReady(hasCantoneseVoice())), []);

  const current: Card | undefined = queue[0];
  const hanzi = current?.word.hanzi ?? null;

  // Keyed on the card object, not the word, so a missed card that comes
  // back around is spoken again.
  useEffect(() => {
    if (hanzi && voiceReady) speakCantonese(hanzi);
  }, [current, hanzi, voiceReady]);

  useEffect(() => () => window.speechSynthesis?.cancel(), []);

  function handleGrade(knewIt: boolean) {
    const [card, ...rest] = queue;
    let next = rest;
    if (!knewIt) {
      const misses = card.misses + 1;
      if (misses < MAX_MISSES) next = [...rest, { word: card.word, misses }];
    }
    setQueue(next);
    setFlipped(false);
  }

  if (!current) {
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

  const audioUnavailable = !voiceReady
    ? "No Cantonese voice is installed in this browser"
    : !hanzi
      ? "No audio for this word"
      : null;

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
        <div className="flashcard-audio">
          <button
            className="flashcard-audio-button"
            onClick={() => hanzi && speakCantonese(hanzi)}
            disabled={audioUnavailable !== null}
            title={audioUnavailable ?? "Play audio"}
          >
            🔊 Play audio
          </button>
          {audioUnavailable && <span className="flashcard-audio-note">{audioUnavailable}</span>}
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
