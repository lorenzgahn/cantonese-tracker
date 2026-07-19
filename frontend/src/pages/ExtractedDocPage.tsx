import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { exportDialogue } from "../api/client";

export function ExtractedDocPage() {
  const { dialogueId = "" } = useParams<{ dialogueId: string }>();
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    exportDialogue(dialogueId)
      .then(setText)
      .catch((e: Error) => setError(e.message));
  }, [dialogueId]);

  function download() {
    if (text === null) return;
    const blob = new Blob([text], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${dialogueId}.md`;
    a.click();
    URL.revokeObjectURL(url);
  }

  if (error) return <p className="error">Failed to load document: {error}</p>;
  if (text === null) return <p>Loading…</p>;

  return (
    <div className="doc-page">
      <div className="page-header">
        <h1>Extracted jyutping doc</h1>
        <div>
          <button onClick={download}>Download .md</button>{" "}
          <Link to={`/dialogues/${dialogueId}/review`}>Back to Review</Link>
        </div>
      </div>
      <pre className="extracted-doc">{text}</pre>
    </div>
  );
}
