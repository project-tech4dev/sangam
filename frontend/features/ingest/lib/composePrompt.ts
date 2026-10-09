export type ImportTask = "funder" | "ngo" | "news";
export type NewsSource = "India CSR" | "GDELT";

/** "A", "A and B", "A, B and C". */
export function listNames(names: string[]): string {
  if (names.length <= 1) return names.join("");
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

/** The request a task card sends: the same words staff typed before, so the agent sees no change. */
export function composePrompt(task: ImportTask, names: string[], news: { source: NewsSource; count: number }): string {
  if (task === "news") return `Run an import from ${news.source}, ${news.count} articles`;
  if (task === "ngo") return `Legal and operational standing of the NGOs ${listNames(names)}`;
  return `Funding profile for ${listNames(names)}`;
}
