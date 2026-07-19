import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { deleteDialogue, listDialogues } from "../api/client";
import type { Dialogue } from "../types";

const SOURCE_TYPE_LABELS: Record<string, string> = {
  structured_pdf: "Structured PDF",
  hanzi_narrative: "Hanzi narrative",
  legacy_annotated: "Legacy annotated",
  plain_jyutping: "Plain jyutping",
  unknown: "Unknown",
};

function flaggedCount(dialogue: Dialogue): number {
  const seen = new Set<string>();
  for (const line of dialogue.lines) {
    for (const w of line.words) {
      if (w.status === "learning") seen.add(w.word_id);
    }
  }
  return seen.size;
}

export function DialogueLibraryPage() {
  const [dialogues, setDialogues] = useState<Dialogue[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    listDialogues()
      .then(setDialogues)
      .catch((e: Error) => setError(e.message));
  }, []);

  // Closes the row menu on any click outside it — a lightweight stand-in
  // for a real popover library, adequate for this single menu at a time.
  useEffect(() => {
    if (openMenuId === null) return;
    function handleClickOutside(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpenMenuId(null);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [openMenuId]);

  async function handleDelete(id: string, title: string) {
    setOpenMenuId(null);
    if (!confirm(`Delete "${title}"? This can't be undone.`)) return;
    await deleteDialogue(id);
    setDialogues((prev) => prev && prev.filter((d) => d.id !== id));
  }

  if (error) return <p className="error">Failed to load dialogues: {error}</p>;
  if (!dialogues) return <p>Loading…</p>;

  return (
    <div className="library-page">
      <div className="page-header">
        <h1>Dialogue Library</h1>
        <Link to="/import">+ Import a new dialogue</Link>
      </div>

      {dialogues.length === 0 && <p>No dialogues imported yet.</p>}

      <table className="library-table">
        <thead>
          <tr>
            <th>Title</th>
            <th>Series</th>
            <th>Level</th>
            <th>Source</th>
            <th>Imported</th>
            <th>Lines</th>
            <th>Flagged words</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {dialogues.map((d) => (
            <tr key={d.id}>
              <td>{d.title}</td>
              <td>{d.series}</td>
              <td>{d.level ?? "—"}</td>
              <td>{SOURCE_TYPE_LABELS[d.source_type] ?? d.source_type}</td>
              <td>{d.imported_at || "—"}</td>
              <td>{d.lines.length}</td>
              <td>{flaggedCount(d)}</td>
              <td>
                <Link to={`/dialogues/${d.id}/review`}>Review</Link>{" "}
                <Link to={`/dialogues/${d.id}/doc`}>Doc</Link>{" "}
                <span className="row-menu" ref={openMenuId === d.id ? menuRef : undefined}>
                  <button
                    className="row-menu-button"
                    title="More actions"
                    onClick={() => setOpenMenuId(openMenuId === d.id ? null : d.id)}
                  >
                    ⋯
                  </button>
                  {openMenuId === d.id && (
                    <div className="row-menu-dropdown">
                      <button className="row-menu-delete" onClick={() => handleDelete(d.id, d.title)}>
                        Delete
                      </button>
                    </div>
                  )}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
