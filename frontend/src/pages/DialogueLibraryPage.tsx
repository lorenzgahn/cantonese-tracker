import { useEffect, useMemo, useRef, useState } from "react";
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

type SortColumn = "title" | "series" | "level" | "source";
type SortDir = "asc" | "desc";

const ALL = "__all__";

export function DialogueLibraryPage() {
  const [dialogues, setDialogues] = useState<Dialogue[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);

  const [sortBy, setSortBy] = useState<SortColumn>("title");
  const [sortDir, setSortDir] = useState<SortDir>("asc");
  const [titleFilter, setTitleFilter] = useState("");
  const [seriesFilter, setSeriesFilter] = useState(ALL);
  const [levelFilter, setLevelFilter] = useState(ALL);
  const [sourceFilter, setSourceFilter] = useState(ALL);

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

  // Filter dropdown options are derived from whatever's actually in the
  // library, not a hardcoded list — so a Series/Source that's never been
  // imported never shows up as a dead option.
  const seriesOptions = useMemo(
    () => Array.from(new Set((dialogues ?? []).map((d) => d.series))).sort(),
    [dialogues],
  );
  const levelOptions = useMemo(
    () =>
      Array.from(new Set((dialogues ?? []).map((d) => d.level).filter((l): l is number => l !== null))).sort(
        (a, b) => a - b,
      ),
    [dialogues],
  );
  const sourceOptions = useMemo(
    () => Array.from(new Set((dialogues ?? []).map((d) => d.source_type))).sort(),
    [dialogues],
  );

  const visibleDialogues = useMemo(() => {
    if (!dialogues) return [];
    const filtered = dialogues.filter((d) => {
      if (titleFilter.trim() && !d.title.toLowerCase().includes(titleFilter.trim().toLowerCase())) return false;
      if (seriesFilter !== ALL && d.series !== seriesFilter) return false;
      if (levelFilter !== ALL) {
        if (levelFilter === "blank" ? d.level !== null : d.level !== Number(levelFilter)) return false;
      }
      if (sourceFilter !== ALL && d.source_type !== sourceFilter) return false;
      return true;
    });

    const dir = sortDir === "asc" ? 1 : -1;
    return [...filtered].sort((a, b) => {
      switch (sortBy) {
        case "title":
          return a.title.localeCompare(b.title) * dir;
        case "series":
          return a.series.localeCompare(b.series) * dir;
        case "level":
          // Blank levels sort before any numbered level, in either direction.
          return ((a.level ?? -1) - (b.level ?? -1)) * dir;
        case "source":
          return a.source_type.localeCompare(b.source_type) * dir;
      }
    });
  }, [dialogues, titleFilter, seriesFilter, levelFilter, sourceFilter, sortBy, sortDir]);

  function handleSort(column: SortColumn) {
    if (sortBy === column) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortBy(column);
      setSortDir("asc");
    }
  }

  function sortIndicator(column: SortColumn) {
    if (sortBy !== column) return null;
    return <span className="sort-indicator">{sortDir === "asc" ? " ▲" : " ▼"}</span>;
  }

  function clearFilters() {
    setTitleFilter("");
    setSeriesFilter(ALL);
    setLevelFilter(ALL);
    setSourceFilter(ALL);
  }

  const filtersActive =
    titleFilter.trim() !== "" || seriesFilter !== ALL || levelFilter !== ALL || sourceFilter !== ALL;

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

      {dialogues.length > 0 && (
        <div className="library-filters">
          <input
            className="library-filter-title"
            type="text"
            placeholder="Filter by title…"
            value={titleFilter}
            onChange={(e) => setTitleFilter(e.target.value)}
          />
          <select value={seriesFilter} onChange={(e) => setSeriesFilter(e.target.value)}>
            <option value={ALL}>All series</option>
            {seriesOptions.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <select value={levelFilter} onChange={(e) => setLevelFilter(e.target.value)}>
            <option value={ALL}>All levels</option>
            {levelOptions.map((l) => (
              <option key={l} value={l}>
                {l}
              </option>
            ))}
            <option value="blank">No level</option>
          </select>
          <select value={sourceFilter} onChange={(e) => setSourceFilter(e.target.value)}>
            <option value={ALL}>All sources</option>
            {sourceOptions.map((s) => (
              <option key={s} value={s}>
                {SOURCE_TYPE_LABELS[s] ?? s}
              </option>
            ))}
          </select>
          {filtersActive && (
            <button className="library-filters-clear" onClick={clearFilters}>
              Clear filters
            </button>
          )}
        </div>
      )}

      {dialogues.length > 0 && (
        <table className="library-table">
          <thead>
            <tr>
              <th>
                <button className="sortable-header" onClick={() => handleSort("title")}>
                  Title{sortIndicator("title")}
                </button>
              </th>
              <th>
                <button className="sortable-header" onClick={() => handleSort("series")}>
                  Series{sortIndicator("series")}
                </button>
              </th>
              <th>
                <button className="sortable-header" onClick={() => handleSort("level")}>
                  Level{sortIndicator("level")}
                </button>
              </th>
              <th>
                <button className="sortable-header" onClick={() => handleSort("source")}>
                  Source{sortIndicator("source")}
                </button>
              </th>
              <th>Imported</th>
              <th>Lines</th>
              <th>Flagged words</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {visibleDialogues.length === 0 && (
              <tr>
                <td colSpan={8}>No dialogues match these filters.</td>
              </tr>
            )}
            {visibleDialogues.map((d) => (
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
      )}
    </div>
  );
}
