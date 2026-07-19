import type { DetectedInputType, Dialogue, DialogueSeries, VocabEntry, VocabStatus } from "../types";

const BASE_URL = "http://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, init);
  if (!res.ok) {
    throw new Error(`${init?.method ?? "GET"} ${path} failed: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

async function requestText(path: string, init?: RequestInit): Promise<string> {
  const res = await fetch(`${BASE_URL}${path}`, init);
  if (!res.ok) {
    throw new Error(`${init?.method ?? "GET"} ${path} failed: ${res.status}`);
  }
  return res.text();
}

function postJson<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

// --- Dialogues / Review ---

export function listDialogues(): Promise<Dialogue[]> {
  return request<Dialogue[]>("/api/dialogues");
}

export function getDialogue(dialogueId: string): Promise<Dialogue> {
  return request<Dialogue>(`/api/dialogues/${dialogueId}`);
}

export function exportDialogue(dialogueId: string): Promise<string> {
  return requestText(`/api/dialogues/${dialogueId}/export`);
}

export function clickWord(dialogueId: string, wordId: string): Promise<VocabEntry> {
  return request<VocabEntry>(`/api/dialogues/${dialogueId}/words/${wordId}/click`, {
    method: "POST",
  });
}

export function unclickWord(dialogueId: string, wordId: string): Promise<VocabEntry> {
  return request<VocabEntry>(`/api/dialogues/${dialogueId}/words/${wordId}/unclick`, {
    method: "POST",
  });
}

export function reevaluateWord(dialogueId: string, wordId: string): Promise<Dialogue> {
  return request<Dialogue>(`/api/dialogues/${dialogueId}/words/${wordId}/reevaluate`, {
    method: "POST",
  });
}

// Sets word_id's definition for this dialogue only — the same jyutping
// can mean something different in another dialogue, which keeps its own
// definition (or the shared default) untouched.
export function setDefinitionOverride(dialogueId: string, wordId: string, definition: string): Promise<Dialogue> {
  return postJson(`/api/dialogues/${dialogueId}/words/${wordId}/definition`, { definition });
}

export function mergeWithNext(dialogueId: string, lineId: string, wordId: string): Promise<Dialogue> {
  return request<Dialogue>(`/api/dialogues/${dialogueId}/lines/${lineId}/words/${wordId}/merge-next`, {
    method: "POST",
  });
}

export function splitWord(dialogueId: string, lineId: string, wordId: string): Promise<Dialogue> {
  return request<Dialogue>(`/api/dialogues/${dialogueId}/lines/${lineId}/words/${wordId}/split`, {
    method: "POST",
  });
}

export function editJyutping(dialogueId: string, lineId: string, wordId: string, jyutping: string): Promise<Dialogue> {
  return postJson(`/api/dialogues/${dialogueId}/lines/${lineId}/words/${wordId}/jyutping`, { jyutping });
}

export function finishReview(dialogueId: string, clickedWordIds: string[]): Promise<void> {
  return postJson(`/api/dialogues/${dialogueId}/finish-review`, {
    clicked_word_ids: clickedWordIds,
  });
}

export function deleteDialogue(dialogueId: string): Promise<void> {
  return request(`/api/dialogues/${dialogueId}`, { method: "DELETE" });
}

// --- Import ---

export function detectInputType(args: { text?: string; filename?: string }): Promise<DetectedInputType> {
  return postJson<{ detected_type: DetectedInputType }>("/api/import/detect", args).then(
    (r) => r.detected_type,
  );
}

interface ImportResponse {
  dialogue_id: string;
  title: string;
  line_count: number;
}

export async function importPdf(
  file: File,
  series: DialogueSeries,
  level: number | null,
): Promise<ImportResponse> {
  const form = new FormData();
  form.append("file", file);
  form.append("series", series);
  if (level !== null) form.append("level", String(level));
  const res = await fetch(`${BASE_URL}/api/import/pdf`, { method: "POST", body: form });
  if (!res.ok) throw new Error(`import/pdf failed: ${res.status}`);
  return res.json();
}

export function importHanziNarrative(
  text: string,
  title: string,
  series: DialogueSeries,
  level: number | null,
): Promise<ImportResponse> {
  return postJson("/api/import/hanzi-narrative", { text, title, series, level });
}

export function importLegacyAnnotated(
  text: string,
  title: string,
  series: DialogueSeries,
  level: number | null,
): Promise<ImportResponse> {
  return postJson("/api/import/legacy-annotated", { text, title, series, level });
}

export function importPlainJyutping(
  text: string,
  title: string,
  series: DialogueSeries,
  level: number | null,
): Promise<ImportResponse> {
  return postJson("/api/import/plain-jyutping", { text, title, series, level });
}

// --- Vocab ---

export function listVocab(status?: VocabStatus, sortBy?: string): Promise<VocabEntry[]> {
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  if (sortBy) params.set("sort_by", sortBy);
  const qs = params.toString();
  return request<VocabEntry[]>(`/api/vocab${qs ? `?${qs}` : ""}`);
}

export function promoteWord(wordId: string): Promise<VocabEntry> {
  return request<VocabEntry>(`/api/vocab/${wordId}/promote`, { method: "POST" });
}

export function upsertWord(
  wordId: string,
  body: { hanzi?: string | null; definition?: string | null; status: VocabStatus },
): Promise<VocabEntry> {
  return request<VocabEntry>(`/api/vocab/${wordId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function deleteWord(wordId: string): Promise<void> {
  return request(`/api/vocab/${wordId}`, { method: "DELETE" });
}
