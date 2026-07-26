export type VocabStatus = "known" | "learning" | "learned";
export type DefinitionSource = "dictionary" | "llm" | "manual";

export interface WordToken {
  token_id: string;
  word_id: string;
  jyutping: string;
  hanzi: string | null;
  trailing_punctuation: string;
  status: VocabStatus;
  definition: string | null;
  source_of_definition: DefinitionSource | null;
}

export interface Line {
  id: string;
  speaker: string | null;
  words: WordToken[];
}

export interface Dialogue {
  id: string;
  title: string;
  lines: Line[];
  source_type: string;
  imported_at: string;
  series: string;
  level: number | null;
  link_url: string | null;
}

export type DialogueSeries = "Hambaanglaang" | "Cantonese Conversations" | "Other";

export interface VocabEntry {
  id: string;
  hanzi: string | null;
  definition: string | null;
  source_of_definition: DefinitionSource | null;
  status: VocabStatus;
  first_seen_dialogue_id: string | null;
  first_seen_date: string | null;
  last_seen_date: string | null;
  times_seen: number;
}

export type DetectedInputType =
  | "structured_pdf"
  | "hanzi_narrative"
  | "legacy_annotated"
  | "plain_jyutping"
  | "unknown";
