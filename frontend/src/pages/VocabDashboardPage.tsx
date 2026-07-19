import { useEffect, useState } from "react";
import { deleteWord, listVocab, promoteWord } from "../api/client";
import { GrowthChart } from "../components/GrowthChart";
import type { VocabEntry, VocabStatus } from "../types";

type StatusFilter = VocabStatus | "all";

export function VocabDashboardPage() {
  const [entries, setEntries] = useState<VocabEntry[] | null>(null);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [sortBy, setSortBy] = useState("last_seen_date");
  const [error, setError] = useState<string | null>(null);

  function reload() {
    listVocab(statusFilter === "all" ? undefined : statusFilter, sortBy)
      .then(setEntries)
      .catch((e: Error) => setError(e.message));
  }

  useEffect(reload, [statusFilter, sortBy]);

  async function handlePromote(wordId: string) {
    await promoteWord(wordId);
    reload();
  }

  async function handleDelete(wordId: string) {
    await deleteWord(wordId);
    reload();
  }

  if (error) return <p className="error">Failed to load vocab: {error}</p>;

  return (
    <div className="vocab-dashboard">
      <h1>Vocab Dashboard</h1>

      {entries && <GrowthChart entries={entries} />}

      <div className="vocab-controls">
        <label>
          Status:
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}>
            <option value="all">All</option>
            <option value="known">Known</option>
            <option value="learning">Learning</option>
            <option value="learned">Learned</option>
          </select>
        </label>
        <label>
          Sort by:
          <select value={sortBy} onChange={(e) => setSortBy(e.target.value)}>
            <option value="last_seen_date">Last seen</option>
            <option value="first_seen_date">First seen</option>
            <option value="times_seen">Times seen</option>
            <option value="id">Jyutping (A–Z)</option>
          </select>
        </label>
      </div>

      {!entries ? (
        <p>Loading…</p>
      ) : (
        <table className="vocab-table">
          <thead>
            <tr>
              <th>Jyutping</th>
              <th>Definition</th>
              <th>Status</th>
              <th>Times seen</th>
              <th>Last seen</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {entries.map((e) => (
              <tr key={e.id}>
                <td>{e.id}</td>
                <td>{e.definition ?? "—"}</td>
                <td>{e.status}</td>
                <td>{e.times_seen}</td>
                <td>{e.last_seen_date ?? "—"}</td>
                <td>
                  {e.status === "learning" && (
                    <button onClick={() => handlePromote(e.id)}>Mark learned</button>
                  )}{" "}
                  <button onClick={() => handleDelete(e.id)}>Delete</button>
                </td>
              </tr>
            ))}
            {entries.length === 0 && (
              <tr>
                <td colSpan={6}>No words match this filter.</td>
              </tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  );
}
