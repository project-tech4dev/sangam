export type ImportTask = "funder" | "ngo" | "news";
export type NewsSource = "India CSR" | "GDELT";

/** "A", "A and B", "A, B and C". */
export function listNames(names: string[]): string {
  if (names.length <= 1) return names.join("");
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

/** Doc Vault files to read before the web: the organisation's slug and the document ids. */
export type VaultPick = { org: string; orgName: string; ids: number[] };

/** The request a task card sends: the same words staff typed before, so the agent sees no change. */
export function composePrompt(
  task: ImportTask,
  names: string[],
  news: { source: NewsSource; count: number },
  vault?: VaultPick,
): string {
  if (task === "news") return `Run an import from ${news.source}, ${news.count} articles`;
  const ask = task === "ngo" ? `Legal and operational standing of the NGOs ${listNames(names)}` : `Funding profile for ${listNames(names)}`;
  if (!vault?.ids.length) return ask;
  const docs = listNames(vault.ids.map(String));
  return `${ask}, reading ${vault.orgName}'s Doc Vault first (org ${vault.org}, document${vault.ids.length === 1 ? "" : "s"} ${docs})`;
}
