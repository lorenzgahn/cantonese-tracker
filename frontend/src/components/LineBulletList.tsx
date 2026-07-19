import type { WordToken as WordTokenType } from "../types";
import { WordToken } from "./WordToken";

interface Props {
  words: WordTokenType[];
  onToggle: (wordId: string) => void;
  onReevaluate: (wordId: string) => void;
  onMarkLearned: (wordId: string) => void;
  onMergeNext: (wordId: string) => void;
  onSplit: (wordId: string) => void;
  onEditDefinition: (wordId: string, definition: string) => void;
  onEditJyutping: (wordId: string, jyutping: string) => void;
}

/** Bullet list of flagged (learning or learned) words for a single line,
 * rendered directly underneath that line. Empty (renders nothing) until
 * at least one word in the line has been clicked. Marking a word learned
 * doesn't remove its bullet — it stays visible with a reduced action set
 * (see WordToken); only unflagging all the way back to known, done by
 * clicking the inline word in the text above, removes it. These bullets
 * are read-only aside from their action buttons. Deduped by word_id — a
 * word repeated within the line (e.g. 行山 said twice in one turn) gets
 * one entry, not one per occurrence. Merge is only offered when the word
 * isn't the last token in the line — it always combines with whatever
 * token comes right after it in the original (undeduped) order, not the
 * next *flagged* word. */
export function LineBulletList({
  words,
  onToggle,
  onReevaluate,
  onMarkLearned,
  onMergeNext,
  onSplit,
  onEditDefinition,
  onEditJyutping,
}: Props) {
  const seen = new Set<string>();
  const flagged = words
    .map((w, index) => ({ w, index }))
    .filter(({ w }) => w.status === "learning" || w.status === "learned")
    .filter(({ w }) => {
      if (seen.has(w.word_id)) return false;
      seen.add(w.word_id);
      return true;
    });
  if (flagged.length === 0) return null;

  return (
    <ul className="line-bullets">
      {flagged.map(({ w, index }) => (
        <WordToken
          key={w.token_id}
          token={w}
          variant="bullet"
          onToggle={onToggle}
          onReevaluate={onReevaluate}
          onMarkLearned={onMarkLearned}
          onMergeNext={index < words.length - 1 ? onMergeNext : undefined}
          onSplit={onSplit}
          onEditDefinition={onEditDefinition}
          onEditJyutping={onEditJyutping}
        />
      ))}
    </ul>
  );
}
