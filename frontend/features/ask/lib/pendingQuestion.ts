// A question typed on the public /ask preview survives the Google sign-in round-trip
// here, and the workspace prefills it (never sends it). Storage can be unavailable
// (private windows, blocked site data); losing the question then is acceptable.

const KEY = "sangam:pendingQuestion";

export function savePendingQuestion(question: string) {
  try {
    sessionStorage.setItem(KEY, question);
  } catch {}
}

/** Read once and clear, so a refresh does not bring the question back. */
export function takePendingQuestion(): string | null {
  try {
    const question = sessionStorage.getItem(KEY);
    sessionStorage.removeItem(KEY);
    return question?.trim() || null;
  } catch {
    return null;
  }
}
