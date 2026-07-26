import { useEffect, useRef, useState } from "react";
import type { WordToken as WordTokenType } from "../types";

interface Props {
  token: WordTokenType;
  variant: "inline" | "bullet";
  onToggle: (wordId: string) => void;
  onReevaluate?: (wordId: string) => void;
  onMarkLearned?: (wordId: string) => void;
  onMergeNext?: (wordId: string) => void;
  onSplit?: (wordId: string) => void;
  onEditDefinition?: (wordId: string, definition: string) => void;
  onEditJyutping?: (wordId: string, jyutping: string) => void;
}

/**
 * A single clickable word span. Inline (within a line's running text)
 * onToggle cycles between known/learning/learned — the caller checks the
 * word's current status and calls the right endpoint. Bullet entries
 * (per-line / per-dialogue flagged-word lists) are not clickable as a
 * whole; every action (re-evaluate, mark as learned, merge, split, edit)
 * lives behind a single "edit" button instead of one button each, since
 * with all of them inline the row got too busy — so flagging state can
 * only change from the inline word in the text, never a bullet.
 * Bullets stay visible for both "learning" and "learned" words — marking
 * one learned doesn't remove it from the list, it just swaps which
 * menu items are offered: merge/split/edit-jyutping only make sense
 * while still actively segmenting/defining a word, so they (and "mark as
 * learned" itself) only show while still "learning"; re-evaluate and
 * edit-definition stay available either way, in case the definition
 * needs touching up after the fact. Split only makes sense for a
 * multi-syllable word (there's nothing to split a single syllable into),
 * so it's hidden rather than shown disabled when the word is only one
 * syllable. The edit actions use a native prompt() pre-filled with the
 * current value — consistent with the delete confirmation elsewhere in
 * this app, and simplest for a single-user tool.
 */
export function WordToken({
  token,
  variant,
  onToggle,
  onReevaluate,
  onMarkLearned,
  onMergeNext,
  onSplit,
  onEditDefinition,
  onEditJyutping,
}: Props) {
  const isLearning = token.status === "learning";
  const isLearned = token.status === "learned";
  const isMultiSyllable = token.jyutping.trim().includes(" ");

  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLSpanElement | null>(null);

  useEffect(() => {
    if (!menuOpen) return;
    function handleClickOutside(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [menuOpen]);

  if (variant === "inline") {
    const statusClass = isLearning ? "flagged" : isLearned ? "learned" : "";
    return (
      <span onClick={() => onToggle(token.word_id)} className={`word-token ${statusClass}`.trim()}>
        {token.jyutping}
        {token.trailing_punctuation}
      </span>
    );
  }

  function runAndClose(action: () => void) {
    setMenuOpen(false);
    action();
  }

  return (
    <li className="word-bullet">
      <span className="word-bullet-jyutping">{token.jyutping}</span>
      {token.definition && <span className="word-bullet-def"> — {token.definition}</span>}
      <span className="word-edit-menu" ref={menuOpen ? menuRef : undefined}>
        <button
          className="word-bullet-action"
          title="Edit"
          onClick={(e) => {
            e.stopPropagation();
            setMenuOpen((v) => !v);
          }}
        >
          edit
        </button>
        {menuOpen && (
          <div className="word-edit-menu-dropdown">
            {onReevaluate && (
              <button
                className="word-edit-menu-item"
                title="Re-evaluate definition"
                onClick={(e) => {
                  e.stopPropagation();
                  runAndClose(() => onReevaluate(token.word_id));
                }}
              >
                re-evaluate
              </button>
            )}
            {onMarkLearned && isLearning && (
              <button
                className="word-edit-menu-item"
                title="Mark as learned — shows green in the text instead of red, stays out of active review"
                onClick={(e) => {
                  e.stopPropagation();
                  runAndClose(() => onMarkLearned(token.word_id));
                }}
              >
                mark as learned
              </button>
            )}
            {onMergeNext && isLearning && (
              <button
                className="word-edit-menu-item"
                title="Merge with the next word — use when a multi-word phrase was split up"
                onClick={(e) => {
                  e.stopPropagation();
                  runAndClose(() => onMergeNext(token.word_id));
                }}
              >
                merge with next
              </button>
            )}
            {onSplit && isLearning && isMultiSyllable && (
              <button
                className="word-edit-menu-item"
                title="Split into individual syllables — use when this was merged wrong"
                onClick={(e) => {
                  e.stopPropagation();
                  runAndClose(() => onSplit(token.word_id));
                }}
              >
                split
              </button>
            )}
            {onEditDefinition && (
              <button
                className="word-edit-menu-item"
                title="Type your own definition"
                onClick={(e) => {
                  e.stopPropagation();
                  setMenuOpen(false);
                  const next = window.prompt("Edit definition:", token.definition ?? "");
                  if (next === null) return;
                  onEditDefinition(token.word_id, next);
                }}
              >
                edit definition
              </button>
            )}
            {onEditJyutping && isLearning && (
              <button
                className="word-edit-menu-item"
                title="Correct the reading — use when the jyutping itself is wrong"
                onClick={(e) => {
                  e.stopPropagation();
                  setMenuOpen(false);
                  const next = window.prompt("Edit jyutping:", token.jyutping);
                  if (next === null || !next.trim()) return;
                  onEditJyutping(token.word_id, next.trim());
                }}
              >
                edit jyutping
              </button>
            )}
          </div>
        )}
      </span>
    </li>
  );
}
