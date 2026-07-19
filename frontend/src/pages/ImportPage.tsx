import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  detectInputType,
  importHanziNarrative,
  importLegacyAnnotated,
  importPdf,
  importPlainJyutping,
} from "../api/client";
import type { DetectedInputType, DialogueSeries } from "../types";

const TYPE_LABELS: Record<DetectedInputType, string> = {
  structured_pdf: "Structured PDF (table format)",
  hanzi_narrative: "Hanzi-only narrative",
  legacy_annotated: "Legacy annotated ([bracket] + definitions)",
  plain_jyutping: "Plain jyutping (no hanzi)",
  unknown: "Unknown — pick manually",
};

const SERIES_OPTIONS: DialogueSeries[] = ["Hambaanglaang", "Cantonese Conversations", "Other"];

export function ImportPage() {
  const navigate = useNavigate();
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [series, setSeries] = useState<DialogueSeries>("Other");
  const [level, setLevel] = useState<number | null>(null);
  const [detected, setDetected] = useState<DetectedInputType>("unknown");
  const [selectedType, setSelectedType] = useState<DetectedInputType>("unknown");
  const [overridden, setOverridden] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Re-detect whenever the input changes, but don't clobber a manual
  // override the user already made for this input.
  useEffect(() => {
    if (file) {
      setDetected("structured_pdf");
      if (!overridden) setSelectedType("structured_pdf");
      return;
    }
    if (!text.trim()) {
      setDetected("unknown");
      if (!overridden) setSelectedType("unknown");
      return;
    }
    const handle = setTimeout(() => {
      detectInputType({ text }).then((t) => {
        setDetected(t);
        if (!overridden) setSelectedType(t);
      });
    }, 300);
    return () => clearTimeout(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text, file]);

  function handleFileChange(f: File | null) {
    setFile(f);
    setOverridden(false);
    if (f && !title) setTitle(f.name.replace(/\.pdf$/i, ""));
  }

  function handleTypeChange(t: DetectedInputType) {
    setSelectedType(t);
    setOverridden(true);
  }

  // Level only applies to Hambaanglaang — clear it if the user switches
  // away so a stale value doesn't get sent for a series that has none.
  function handleSeriesChange(s: DialogueSeries) {
    setSeries(s);
    if (s !== "Hambaanglaang") setLevel(null);
  }

  async function handleSubmit() {
    setBusy(true);
    setError(null);
    try {
      let result: { dialogue_id: string };
      switch (selectedType) {
        case "structured_pdf":
          if (!file) throw new Error("Choose a PDF file first");
          result = await importPdf(file, series, level);
          break;
        case "hanzi_narrative":
          result = await importHanziNarrative(text, title || "Untitled", series, level);
          break;
        case "legacy_annotated":
          result = await importLegacyAnnotated(text, title || "Untitled", series, level);
          break;
        case "plain_jyutping":
          result = await importPlainJyutping(text, title || "Untitled", series, level);
          break;
        default:
          throw new Error("Pick an input type before importing");
      }
      navigate(`/dialogues/${result.dialogue_id}/review`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="import-page">
      <h1>Import a dialogue</h1>

      <label className="field">
        Title
        <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Untitled" />
      </label>

      <label className="field">
        Series
        <select value={series} onChange={(e) => handleSeriesChange(e.target.value as DialogueSeries)}>
          {SERIES_OPTIONS.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </label>

      {series === "Hambaanglaang" && (
        <label className="field">
          Level
          <input
            type="number"
            min={1}
            value={level ?? ""}
            onChange={(e) => setLevel(e.target.value === "" ? null : Number(e.target.value))}
            placeholder="e.g. 1"
          />
        </label>
      )}

      <label className="field">
        <input
          type="file"
          accept=".pdf"
          onChange={(e) => handleFileChange(e.target.files?.[0] ?? null)}
        />
      </label>

      {!file && (
        <label className="field">
          Or paste text
          <textarea
            rows={12}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Paste a hanzi narrative, plain jyutping, or your legacy-annotated text here…"
          />
        </label>
      )}

      <label className="field">
        Detected type: <strong>{TYPE_LABELS[detected]}</strong>
        <select value={selectedType} onChange={(e) => handleTypeChange(e.target.value as DetectedInputType)}>
          {(Object.keys(TYPE_LABELS) as DetectedInputType[]).map((t) => (
            <option key={t} value={t}>
              {TYPE_LABELS[t]}
            </option>
          ))}
        </select>
      </label>

      {error && <p className="error">{error}</p>}

      <button onClick={handleSubmit} disabled={busy || selectedType === "unknown"}>
        {busy ? "Importing…" : "Import"}
      </button>
    </div>
  );
}
