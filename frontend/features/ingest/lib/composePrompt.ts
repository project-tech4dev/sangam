export type ImportTask = "funder" | "ngo" | "news";

/** What a task card writes into the composer: the same words staff typed before, so the agent sees no change. */
export function leadIn(task: ImportTask): string {
  if (task === "news") return "Get the latest news for everyone in Sangam";
  return task === "ngo" ? "Legal and operational standing of the NGOs " : "Funding profile for ";
}
