export type ImportTask = "funder" | "ngo" | "news" | "calls";

/** A fixed pull, not research: it reads no chosen sources, so no sources step comes before it. */
export const isPull = (task: ImportTask | null) => task === "news" || task === "calls";

/** What a task card writes into the composer: the same words staff typed before, so the agent sees no change. */
export function leadIn(task: ImportTask): string {
  if (task === "news") return "Get the latest news for everyone in Sangam";
  if (task === "calls") return "Check open calls for proposals from every funder in Sangam";
  return task === "ngo" ? "Legal and operational standing of the NGOs " : "Funding profile for ";
}
