// Cantonese audio via the browser's built-in speech synthesis. Speaks
// from hanzi (never displayed — see the jyutping-only UI convention),
// since no browser voice accepts jyutping as input.

function cantoneseVoice(): SpeechSynthesisVoice | undefined {
  if (!("speechSynthesis" in window)) return undefined;
  const voices = window.speechSynthesis.getVoices().filter((v) => /^(zh[-_]HK|yue)/i.test(v.lang));
  // Prefer a voice that runs on this machine over a network one.
  return voices.find((v) => v.localService) ?? voices[0];
}

export function hasCantoneseVoice(): boolean {
  return cantoneseVoice() !== undefined;
}

// Chrome populates the voice list asynchronously, so the first
// getVoices() call can come back empty — callers re-check on this event.
export function onVoicesChanged(callback: () => void): () => void {
  if (!("speechSynthesis" in window)) return () => {};
  window.speechSynthesis.addEventListener("voiceschanged", callback);
  return () => window.speechSynthesis.removeEventListener("voiceschanged", callback);
}

/** Speaks `hanzi` in Cantonese. Deliberately silent when no Cantonese
 * voice is installed — setting only `lang` would let the browser fall
 * back to a Mandarin voice, which is worse than no audio at all. */
export function speakCantonese(hanzi: string): void {
  const voice = cantoneseVoice();
  if (!voice) return;
  const utterance = new SpeechSynthesisUtterance(hanzi);
  utterance.voice = voice;
  utterance.lang = voice.lang;
  utterance.rate = 0.85;
  window.speechSynthesis.cancel();
  window.speechSynthesis.speak(utterance);
}
