import { useEffect, useState } from "react";
import { getSettings, updateSettings } from "../api/client";

export function SettingsPage() {
  const [chunkSize, setChunkSize] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    getSettings()
      .then((s) => setChunkSize(String(s.review_chunk_size)))
      .catch((e: Error) => setError(e.message));
  }, []);

  const parsed = Number(chunkSize);
  const valid = Number.isInteger(parsed) && parsed >= 1 && parsed <= 200;

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setSaved(false);
    setError(null);
    try {
      const updated = await updateSettings({ review_chunk_size: parsed });
      setChunkSize(String(updated.review_chunk_size));
      setSaved(true);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <div className="settings-page">
      <h1>Settings</h1>
      <form className="settings-form" onSubmit={handleSave}>
        <label htmlFor="review-chunk-size">Flashcard checkpoint size</label>
        <p className="settings-help">
          How many flagged words to read past before the Review page offers a "Review past N words" flashcard
          button.
        </p>
        <input
          id="review-chunk-size"
          type="number"
          min={1}
          max={200}
          value={chunkSize}
          onChange={(e) => {
            setChunkSize(e.target.value);
            setSaved(false);
          }}
        />
        <button type="submit" className="settings-save-button" disabled={!valid}>
          Save
        </button>
        {saved && <span className="settings-saved">Saved</span>}
        {!valid && chunkSize !== "" && <span className="error">Enter a whole number from 1 to 200.</span>}
        {error && <span className="error">Failed: {error}</span>}
      </form>
    </div>
  );
}
