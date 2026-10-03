import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  clickWord,
  editJyutping,
  finishReview,
  getDialogue,
  mergeWithNext,
  normalizeUrl,
  promoteWord,
  recordStudySession,
  reevaluateWord,
  setDefinitionOverride,
  setDialogueLink,
  splitWord,
  unclickWord,
} from "../api/client";
import { DialogueBulletList } from "../components/DialogueBulletList";
import { FlashcardStudy } from "../components/FlashcardStudy";
import { LineBulletList } from "../components/LineBulletList";
import { WordToken } from "../components/WordToken";
import type { Dialogue, VocabEntry } from "../types";

export function ReviewPage() {
  const { dialogueId = "demo" } = useParams<{ dialogueId: string }>();
  const navigate = useNavigate();
  const [dialogue, setDialogue] = useState<Dialogue | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [finishing, setFinishing] = useState(false);
  const [studying, setStudying] = useState(false);

  useEffect(() => {
    setDialogue(null);
    getDialogue(dialogueId)
      .then(setDialogue)
      .catch((e: Error) => setError(e.message));
  }, [dialogueId]);

  // Applying the server's confirmed status to every occurrence of this
  // word_id across the whole dialogue is what keeps the inline span, the
  // per-line bullet, and the dialogue-aggregate bullet all in sync — they
  // are three renderings of this one tokens structure, not separate state.
  function applyEntry(wordId: string, entry: VocabEntry) {
    setDialogue((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        lines: prev.lines.map((line) => ({
          ...line,
          words: line.words.map((w) =>
            w.word_id === wordId
              ? {
                  ...w,
                  status: entry.status,
                  definition: entry.definition,
                  source_of_definition: entry.source_of_definition,
                }
              : w,
          ),
        })),
      };
    });
  }

  // Clicking the inline word toggles it: flags an unflagged (known) word
  // as learning; unflags a learning *or* learned word straight back to
  // known — checked against the word's live status in the current
  // dialogue state. Unflagging never happens from the bullet lists,
  // since a bullet click is reserved for its explicit action buttons
  // (re-evaluate, mark as learned, edit, etc).
  function currentStatus(wordId: string): string | undefined {
    return dialogue?.lines.flatMap((l) => l.words).find((w) => w.word_id === wordId)?.status;
  }

  async function handleToggle(wordId: string) {
    const status = currentStatus(wordId);
    const entry =
      status === "learning" || status === "learned"
        ? await unclickWord(dialogueId, wordId)
        : await clickWord(dialogueId, wordId);
    applyEntry(wordId, entry);
  }

  // Marks a word learned — same transition as promoting on the Vocab
  // Dashboard, just reachable from a bullet's own action here. Doesn't
  // remove the bullet (see LineBulletList/DialogueBulletList) — it stays
  // visible with a reduced action set, turning green inline instead of
  // red until unflagged back to known via the inline word.
  async function handleMarkLearned(wordId: string) {
    const entry = await promoteWord(wordId);
    applyEntry(wordId, entry);
  }

  // Discards whatever definition is currently shown for this word and
  // resolves a fresh one — for when it's just wrong, not a segmentation
  // problem. Refreshes this dialogue's own override if it has one,
  // otherwise the shared global default (see reevaluate_word), so
  // whole-dialogue replacement rather than applyEntry.
  async function handleReevaluate(wordId: string) {
    const updated = await reevaluateWord(dialogueId, wordId);
    setDialogue(updated);
  }

  // Fixes a bad segmentation (e.g. "li1 paai4" split into two words that
  // should have been one, "lately") by merging with the next token in the
  // line. Token structure changes, so replace the whole dialogue rather
  // than patching — token_ids shift and word_ids change.
  async function handleMergeNext(lineId: string, wordId: string) {
    const updated = await mergeWithNext(dialogueId, lineId, wordId);
    setDialogue(updated);
  }

  // Undoes an accidental merge by exploding a word into one token per
  // syllable — from there, merge the correct adjacent pieces back
  // together by hand. Same whole-dialogue replacement as merge, since
  // token structure changes.
  async function handleSplit(lineId: string, wordId: string) {
    const updated = await splitWord(dialogueId, lineId, wordId);
    setDialogue(updated);
  }

  // Overwrites the definition with exactly what the user typed — scoped
  // to this dialogue only, since the same jyutping can mean something
  // different elsewhere (see setDefinitionOverride). Status is untouched
  // and stays global. Whole-dialogue replacement like merge/split.
  async function handleEditDefinition(wordId: string, definition: string) {
    const updated = await setDefinitionOverride(dialogueId, wordId, definition);
    setDialogue(updated);
  }

  // Corrects a wrong reading (e.g. "dung6" should have been "tung4") —
  // word_id is jyutping-derived, so this changes the word's identity.
  // Whole-dialogue replacement like merge/split, for the same reason.
  async function handleEditJyutping(lineId: string, wordId: string, jyutping: string) {
    const updated = await editJyutping(dialogueId, lineId, wordId, jyutping);
    setDialogue(updated);
  }

  // Adds, edits, or clears (empty input) this dialogue's link to its
  // original audio/video/source content — settable at import time, or
  // here for dialogues that don't have one yet.
  async function handleEditLink() {
    const next = window.prompt("Link to dialogue content:", dialogue?.link_url ?? "");
    if (next === null) return;
    const updated = await setDialogueLink(dialogueId, next.trim() ? normalizeUrl(next) : null);
    setDialogue(updated);
  }

  // Bumps times_studied on the server once a flashcard deck has been
  // fully cleared (see FlashcardStudy) — full-dialogue replacement is
  // fine here since only that counter changed, no word state.
  async function handleFinishStudySession() {
    const updated = await recordStudySession(dialogueId);
    setDialogue(updated);
  }

  async function handleFinishReview() {
    if (!dialogue) return;
    setFinishing(true);
    const clickedWordIds = [
      ...new Set(
        dialogue.lines.flatMap((l) => l.words).filter((w) => w.status === "learning").map((w) => w.word_id),
      ),
    ];
    try {
      await finishReview(dialogueId, clickedWordIds);
      navigate("/");
    } finally {
      setFinishing(false);
    }
  }

  if (error) return <p className="error">Failed to load dialogue: {error}</p>;
  if (!dialogue) return <p>Loading…</p>;

  // Same flagged-and-deduped set DialogueBulletList renders below — the
  // flashcard deck studies exactly what that section already shows.
  const seenWordIds = new Set<string>();
  const flaggedWords = dialogue.lines
    .flatMap((line) => line.words)
    .filter((w) => w.status === "learning" || w.status === "learned")
    .filter((w) => {
      if (seenWordIds.has(w.word_id)) return false;
      seenWordIds.add(w.word_id);
      return true;
    });

  return (
    <div className="review-page">
      <div className="page-header">
        <h1>{dialogue.title}</h1>
        <div className="page-header-links">
          {dialogue.link_url ? (
            <>
              <a href={dialogue.link_url} target="_blank" rel="noopener noreferrer">
                Link to Dialogue
              </a>
              <button className="link-edit-button" onClick={handleEditLink}>
                edit
              </button>
            </>
          ) : (
            <button className="link-edit-button" onClick={handleEditLink}>
              + Add link to dialogue
            </button>
          )}
          <Link to={`/dialogues/${dialogueId}/doc`}>View extracted doc</Link>
        </div>
      </div>

      {dialogue.lines.map((line) => (
        <div key={line.id} className="line">
          {line.speaker && <div className="speaker">{line.speaker}</div>}
          <p className="line-text">
            {line.words.map((w) => (
              <WordToken key={w.token_id} token={w} variant="inline" onToggle={handleToggle} />
            ))}
          </p>
          <LineBulletList
            words={line.words}
            onToggle={handleToggle}
            onReevaluate={handleReevaluate}
            onMarkLearned={handleMarkLearned}
            onMergeNext={(wordId) => handleMergeNext(line.id, wordId)}
            onSplit={(wordId) => handleSplit(line.id, wordId)}
            onEditDefinition={handleEditDefinition}
            onEditJyutping={(wordId, jyutping) => handleEditJyutping(line.id, wordId, jyutping)}
          />
        </div>
      ))}

      <hr />
      <div className="flagged-words-header">
        <h2>All flagged words in this dialogue</h2>
        <div className="flagged-words-header-actions">
          <span className="times-studied">Times studied: {dialogue.times_studied}</span>
          <button className="study-button" onClick={() => setStudying(true)} disabled={flaggedWords.length === 0}>
            Study
          </button>
        </div>
      </div>
      <DialogueBulletList
        dialogue={dialogue}
        onToggle={handleToggle}
        onReevaluate={handleReevaluate}
        onMarkLearned={handleMarkLearned}
        onEditDefinition={handleEditDefinition}
      />

      <button className="finish-review-button" onClick={handleFinishReview} disabled={finishing}>
        {finishing ? "Saving…" : "Finish Review"}
      </button>

      {studying && (
        <FlashcardStudy
          words={flaggedWords}
          onFinish={handleFinishStudySession}
          onClose={() => setStudying(false)}
        />
      )}
    </div>
  );
}
