import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  clickWord,
  editJyutping,
  finishReview,
  getDialogue,
  getSettings,
  mergeWithNext,
  normalizeUrl,
  promoteWord,
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
import type { Dialogue, VocabEntry, WordToken as WordTokenData } from "../types";

function isFlagged(w: WordTokenData): boolean {
  return w.status === "learning" || w.status === "learned";
}

// Where the flashcard checkpoints sit. A checkpoint can only go at the
// end of a line, so sections can't always be exactly chunkSize — this
// picks the set of line breaks whose section sizes are collectively
// closest to chunkSize (least total squared difference), rather than
// greedily cutting at the first line past each multiple of chunkSize,
// which strands a tiny section right after any line with many flagged
// words. The last line always has a checkpoint to catch the remainder.
function computeCheckpointLineIds(dialogue: Dialogue, chunkSize: number): string[] {
  const lastLineId = dialogue.lines[dialogue.lines.length - 1]?.id;
  if (lastLineId === undefined) return [];

  // Only lines that introduce a newly flagged word are worth breaking after.
  const seenWordIds = new Set<string>();
  const candidates: { lineId: string; cumulative: number }[] = [];
  for (const line of dialogue.lines) {
    const before = seenWordIds.size;
    for (const w of line.words) {
      if (isFlagged(w)) seenWordIds.add(w.word_id);
    }
    if (seenWordIds.size > before) candidates.push({ lineId: line.id, cumulative: seenWordIds.size });
  }
  if (candidates.length === 0) return [lastLineId];

  // best[j]: lowest cost of sectioning everything up to candidate j with
  // a break right after it; prev[j]: the break before that one (-1 = start).
  const best: number[] = [];
  const prev: number[] = [];
  for (let j = 0; j < candidates.length; j++) {
    best[j] = (candidates[j].cumulative - chunkSize) ** 2;
    prev[j] = -1;
    for (let i = 0; i < j; i++) {
      const cost = best[i] + (candidates[j].cumulative - candidates[i].cumulative - chunkSize) ** 2;
      if (cost < best[j]) {
        best[j] = cost;
        prev[j] = i;
      }
    }
  }

  const lineIds = [lastLineId];
  for (let j = prev[candidates.length - 1]; j !== -1; j = prev[j]) lineIds.unshift(candidates[j].lineId);
  return lineIds;
}

export function ReviewPage() {
  const { dialogueId = "demo" } = useParams<{ dialogueId: string }>();
  const navigate = useNavigate();
  const [dialogue, setDialogue] = useState<Dialogue | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [finishing, setFinishing] = useState(false);
  const [chunkSize, setChunkSize] = useState<number | null>(null);
  const [checkpointLineIds, setCheckpointLineIds] = useState<string[] | null>(null);
  const [studyWords, setStudyWords] = useState<WordTokenData[] | null>(null);

  useEffect(() => {
    setDialogue(null);
    setCheckpointLineIds(null);
    getDialogue(dialogueId)
      .then(setDialogue)
      .catch((e: Error) => setError(e.message));
  }, [dialogueId]);

  useEffect(() => {
    getSettings()
      .then((s) => setChunkSize(s.review_chunk_size))
      .catch((e: Error) => setError(e.message));
  }, []);

  // Checkpoint positions are frozen as of first load: flagging or
  // unflagging words afterwards only changes how many words each
  // existing button covers, never where the buttons are — until the
  // user asks for fresh, even sections via "Re-split flashcards".
  useEffect(() => {
    if (dialogue && chunkSize !== null && checkpointLineIds === null) {
      setCheckpointLineIds(computeCheckpointLineIds(dialogue, chunkSize));
    }
  }, [dialogue, chunkSize, checkpointLineIds]);

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

  // Each checkpoint drills the same flagged-and-deduped words
  // DialogueBulletList renders below, limited to those first seen since
  // the previous checkpoint. Derived fresh from the tokens on every
  // render, so the counts track flagging/unflagging live.
  const checkpointWords = new Map<string, WordTokenData[]>();
  if (checkpointLineIds !== null) {
    const seenWordIds = new Set<string>();
    let pending: WordTokenData[] = [];
    for (const line of dialogue.lines) {
      for (const w of line.words) {
        if (!isFlagged(w) || seenWordIds.has(w.word_id)) continue;
        seenWordIds.add(w.word_id);
        pending.push(w);
      }
      if (checkpointLineIds.includes(line.id) && pending.length > 0) {
        checkpointWords.set(line.id, pending);
        pending = [];
      }
    }
  }

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
          <button
            className="study-button"
            onClick={() => chunkSize !== null && setCheckpointLineIds(computeCheckpointLineIds(dialogue, chunkSize))}
            disabled={chunkSize === null}
            title="Recompute the flashcard checkpoints into even sections from the words flagged now"
          >
            Re-split flashcards
          </button>
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
          {checkpointWords.has(line.id) && (
            <div className="review-checkpoint">
              <button className="study-button" onClick={() => setStudyWords(checkpointWords.get(line.id)!)}>
                Review past {checkpointWords.get(line.id)!.length}{" "}
                {checkpointWords.get(line.id)!.length === 1 ? "word" : "words"}
              </button>
            </div>
          )}
        </div>
      ))}

      <hr />
      <h2>All flagged words in this dialogue</h2>
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

      {studyWords && <FlashcardStudy words={studyWords} onClose={() => setStudyWords(null)} />}
    </div>
  );
}
