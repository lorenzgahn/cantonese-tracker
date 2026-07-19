import type { Dialogue } from "../types";
import { WordToken } from "./WordToken";

interface Props {
  dialogue: Dialogue;
  onToggle: (wordId: string) => void;
  onReevaluate: (wordId: string) => void;
  onMarkLearned: (wordId: string) => void;
  onEditDefinition: (wordId: string, definition: string) => void;
}

/** Aggregate, deduped bullet list of every flagged (learning or learned)
 * word in the dialogue, rendered once at the end. Unflagging all the way
 * back to known only happens by clicking the inline word in the text —
 * these bullets are read-only aside from their action buttons; marking a
 * word learned keeps its bullet here too, just with a reduced action set
 * (see WordToken). No merge/split/edit-jyutping actions here — those all
 * need a specific line_id (merge's "next word", split/edit-jyutping's
 * dialogue-file mutation), which is ambiguous once you're aggregating
 * across lines. Editing the definition (and marking learned) is fine —
 * both are global by word_id regardless of which line you're looking at
 * it from. */
export function DialogueBulletList({ dialogue, onToggle, onReevaluate, onMarkLearned, onEditDefinition }: Props) {
  const seen = new Set<string>();
  const flagged = dialogue.lines
    .flatMap((line) => line.words)
    .filter((w) => w.status === "learning" || w.status === "learned")
    .filter((w) => {
      if (seen.has(w.word_id)) return false;
      seen.add(w.word_id);
      return true;
    });

  if (flagged.length === 0) {
    return <p className="dialogue-bullets-empty">No words flagged yet — click any word above.</p>;
  }

  return (
    <ul className="dialogue-bullets">
      {flagged.map((w) => (
        <WordToken
          key={w.word_id}
          token={w}
          variant="bullet"
          onToggle={onToggle}
          onReevaluate={onReevaluate}
          onMarkLearned={onMarkLearned}
          onEditDefinition={onEditDefinition}
        />
      ))}
    </ul>
  );
}
