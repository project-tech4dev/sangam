import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/auth-headers", () => ({ authHeaders: async () => ({ Authorization: "Bearer t" }) }));

import { saveResearch } from "../saveActions";
import { deleteResearch, undoSave } from "../staffActions";
import { askLive, fetchImportMessages, fetchImportThreads, isImportId, newImportId } from "../threads";

const fetchMock = vi.fn();
const reply = (status: number, body?: unknown) =>
  ({ ok: status < 400, status, json: async () => (body === undefined ? Promise.reject(new Error("no body")) : body) }) as Response;

beforeEach(() => vi.stubGlobal("fetch", fetchMock));
afterEach(() => {
  fetchMock.mockReset();
  vi.unstubAllGlobals();
});

describe("saveResearch", () => {
  it("posts the decisions for an encoded slug and returns the result", async () => {
    fetchMock.mockResolvedValue(reply(200, { slug: "a b", written: 3 }));
    const out = await saveResearch("a b", { revenue: "keep" });
    expect(out).toMatchObject({ written: 3 });
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe("http://localhost:8010/api/ingest/research/a%20b/save");
    expect(init.method).toBe("POST");
    expect(init.headers).toEqual({ Authorization: "Bearer t", "Content-Type": "application/json" });
    expect(JSON.parse(init.body)).toEqual({ decisions: { revenue: "keep" } });
  });

  it("throws the backend's reason, or the status when it gives none", async () => {
    fetchMock.mockResolvedValueOnce(reply(409, { detail: "Already saved" }));
    await expect(saveResearch("x", {})).rejects.toThrow("Already saved");
    fetchMock.mockResolvedValueOnce(reply(500));
    await expect(saveResearch("x", {})).rejects.toThrow("Saving failed: 500");
  });
});

describe("staff actions", () => {
  it("undoes a save and deletes research by slug", async () => {
    fetchMock.mockResolvedValue(reply(204));
    await undoSave(12);
    await deleteResearch("tata/csr");
    expect(fetchMock.mock.calls.map(([url, init]) => [init.method, url])).toEqual([
      ["POST", "http://localhost:8010/api/ingest/promotions/12/undo"],
      ["DELETE", "http://localhost:8010/api/ingest/research/tata%2Fcsr"],
    ]);
  });

  it("throws the backend's reason when refused", async () => {
    fetchMock.mockResolvedValueOnce(reply(409, { detail: "A row changed since the save" }));
    await expect(undoSave(1)).rejects.toThrow("A row changed since the save");
    fetchMock.mockResolvedValueOnce(reply(500));
    await expect(deleteResearch("x")).rejects.toThrow("DELETE /api/ingest/research/x failed: 500");
  });
});

describe("Import threads", () => {
  it("makes ids it recognises, and refuses others", () => {
    expect(isImportId(newImportId())).toBe(true);
    expect(isImportId("0b6f3c1e-9a7d-4c2b-8e1f-2d3c4b5a6f70")).toBe(false);
    expect(isImportId("import-../x")).toBe(false);
  });

  it("lists past imports with titles", async () => {
    fetchMock.mockResolvedValue(reply(200, [
      { thread_id: "import-1", title: "  Funding   profile for Tata ", created_at: "2026-10-01T00:00:00Z" },
      { thread_id: "import-2", title: null, created_at: "2026-10-02T00:00:00Z" },
    ]));
    expect(await fetchImportThreads()).toEqual([
      { id: "import-1", title: "Funding profile for Tata", createdAt: Date.parse("2026-10-01T00:00:00Z") },
      { id: "import-2", title: "Untitled chat", createdAt: Date.parse("2026-10-02T00:00:00Z") },
    ]);
    fetchMock.mockResolvedValue(reply(500));
    await expect(fetchImportThreads()).rejects.toThrow("Could not load past imports (500).");
  });

  it("loads a thread's messages, none when the server never saw it", async () => {
    fetchMock.mockResolvedValueOnce(reply(200, { messages: [{ id: "m1" }] }));
    expect(await fetchImportMessages("import-1")).toEqual([{ id: "m1" }]);
    fetchMock.mockResolvedValueOnce(reply(404));
    expect(await fetchImportMessages("import-1")).toEqual([]);
    fetchMock.mockResolvedValueOnce(reply(500));
    await expect(fetchImportMessages("import-1")).rejects.toThrow("Could not load this chat (500).");
  });

  it("asks a live run with the time as ISO", async () => {
    fetchMock.mockResolvedValue(reply(200, { answer: "Reading tata.com", kind: "status" }));
    const steps = [{ owner: null, tool: "read_page", running: true }];
    expect(await askLive("import-1", "where are you?", 0, steps)).toEqual({ answer: "Reading tata.com", kind: "status" });
    expect(JSON.parse(fetchMock.mock.calls[0]![1].body)).toEqual({ question: "where are you?", since: null, steps });
    await askLive("import-1", "q", Date.parse("2026-10-01T00:00:00Z"), []);
    expect(JSON.parse(fetchMock.mock.calls[1]![1].body).since).toBe("2026-10-01T00:00:00.000Z");
    fetchMock.mockResolvedValue(reply(503));
    await expect(askLive("import-1", "q", null, [])).rejects.toThrow("Scout could not answer right now (503).");
  });
});
