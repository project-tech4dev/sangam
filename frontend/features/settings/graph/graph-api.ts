import { authHeaders } from "@/lib/api/auth-headers";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8010";

export const BUCKETS = ["org-vault", "source-archive", "staff-sources"] as const;

export type GraphStatus = { enabled: boolean; reason: string };
export type EpisodeResult = { entities: string[]; facts: string[] };
export type Fact = { uuid: string; fact: string; valid_at: string | null; invalid_at: string | null };
export type SearchResult = { query: string; facts: Fact[] };
export type ClearResult = { group_id: string | null; nodes_deleted: number };
export type GraphGroup = { group_id: string; nodes: number; episodes: number };

export type ChunkResult = {
  index: number;
  chars: number;
  status: "added" | "skipped";
  entities: string[];
  facts: string[];
};

export type DocumentResult = {
  key: string;
  status: "added" | "skipped" | "failed";
  chunks: number;
  entities: number;
  facts: number;
  reason: string | null;
  parts: ChunkResult[];
};

export type DocumentEvent =
  | { event: "listing"; bucket: string; prefix: string }
  | { event: "listed"; bucket: string; prefix: string; group_id: string; found: number; reading: string[] }
  | { event: "file_start"; key: string; number: number; total: number }
  | { event: "downloading"; key: string; bytes: number | null }
  | { event: "extracting"; key: string; bytes: number; type: string | null }
  | { event: "chunked"; key: string; chars: number; chunks: number; chunk_chars: number }
  | { event: "chunk_start"; key: string; index: number; total: number; chars: number; episode: string;
      group_id: string; preview: string }
  | { event: "chunk_done"; key: string; total: number; episode: string; chunk: ChunkResult }
  | { event: "file_done"; file: DocumentResult }
  | { event: "done" };

export async function graphRequest<T>(
  method: "GET" | "POST" | "DELETE",
  path: string,
  body?: object,
): Promise<{ data: T } | { error: string }> {
  try {
    const res = await fetch(`${API}/api/graph${path}`, {
      method,
      headers: { ...(await authHeaders()), "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    });
    const payload = await res.json();
    if (!res.ok) return { error: typeof payload.detail === "string" ? payload.detail : `Request failed (${res.status}).` };
    return { data: payload };
  } catch {
    return { error: "Could not reach Sangam. Try again." };
  }
}

export async function graphStream(
  path: string,
  body: object,
  onEvent: (event: DocumentEvent) => void,
  signal?: AbortSignal,
): Promise<string | null> {
  try {
    const res = await fetch(`${API}/api/graph${path}`, {
      method: "POST",
      headers: { ...(await authHeaders()), "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal,
    });
    if (!res.ok || !res.body) {
      const payload = await res.json().catch(() => ({}));
      return typeof payload.detail === "string" ? payload.detail : `Request failed (${res.status}).`;
    }
    const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
    let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += value;
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";
      for (const line of lines) if (line.trim()) onEvent(JSON.parse(line));
    }
    return null;
  } catch {
    if (signal?.aborted) return null;
    return "The connection to Sangam dropped. Chunks already added stay in the graph; run again to continue.";
  }
}
