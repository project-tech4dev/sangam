import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/auth-headers", () => ({ authHeaders: async () => ({ Authorization: "Bearer t" }) }));

import { API } from "@/features/ask/lib/rest";
import { deleteFromVault, listVault, uploadToVault } from "@/features/ask/lib/vault";

const fetchMock = vi.fn();
const reply = (status: number, body: unknown = {}) =>
  fetchMock.mockResolvedValueOnce({ ok: status < 400, status, json: async () => body });
const file = new File(["%PDF"], "accounts.pdf", { type: "application/pdf" });

beforeEach(() => vi.stubGlobal("fetch", fetchMock));
afterEach(() => {
  fetchMock.mockReset();
  vi.unstubAllGlobals();
});

describe("uploadToVault", () => {
  it("asks for a signed URL, PUTs the file there, then records it", async () => {
    reply(200, { upload_url: "https://storage/signed", storage_path: "kabil/accounts.pdf" });
    reply(200);
    reply(201, { id: 9, title: "accounts.pdf" });
    await expect(uploadToVault("kabil", file)).resolves.toEqual({ id: 9, title: "accounts.pdf" });
    const [ask, put, confirm] = fetchMock.mock.calls;
    expect(ask![0]).toBe(`${API}/api/documents/uploads`);
    expect(JSON.parse(ask![1].body)).toEqual({ org: "kabil", filename: "accounts.pdf" });
    expect(put![0]).toBe("https://storage/signed");
    expect(put![1]).toMatchObject({ method: "PUT", headers: { "Content-Type": "application/pdf" }, body: file });
    expect(put![1].headers.Authorization).toBeUndefined();
    expect(confirm![0]).toBe(`${API}/api/documents`);
    expect(JSON.parse(confirm![1].body)).toEqual({ org: "kabil", storage_path: "kabil/accounts.pdf", title: "accounts.pdf" });
  });

  it("sends an untyped file as octet-stream", async () => {
    reply(200, { upload_url: "u", storage_path: "p" });
    reply(200);
    reply(200, {});
    await uploadToVault("kabil", new File(["x"], "notes"));
    expect(fetchMock.mock.calls[1]![1].headers["Content-Type"]).toBe("application/octet-stream");
  });

  it.each([
    [503, "Document storage is not configured on this deployment."],
    [403, "You do not have upload access to this organisation."],
    [500, "Could not start the upload (500)."],
  ])("explains a %i on the first step", async (status, message) => {
    reply(status);
    await expect(uploadToVault("kabil", file)).rejects.toThrow(message);
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("stops when storage refuses the file or the backend does not record it", async () => {
    reply(200, { upload_url: "u", storage_path: "p" });
    reply(400);
    await expect(uploadToVault("kabil", file)).rejects.toThrow("The file did not reach storage (400).");
    reply(200, { upload_url: "u", storage_path: "p" });
    reply(200);
    reply(500);
    await expect(uploadToVault("kabil", file)).rejects.toThrow("Uploaded, but not recorded (500).");
  });
});

describe("listVault", () => {
  it("returns the items for the encoded org", async () => {
    reply(200, { items: [{ id: 1 }] });
    await expect(listVault("a&b")).resolves.toEqual([{ id: 1 }]);
    expect(fetchMock.mock.calls[0]![0]).toBe(`${API}/api/documents?org=a%26b&limit=100`);
  });

  it("throws on failure", async () => {
    reply(500);
    await expect(listVault("kabil")).rejects.toThrow("Could not load the Doc Vault (500).");
  });
});

describe("deleteFromVault", () => {
  it("sends a DELETE for the document with the caller's token", async () => {
    reply(204);
    await expect(deleteFromVault(7)).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenCalledWith(`${API}/api/documents/7`, { method: "DELETE", headers: { Authorization: "Bearer t" } });
  });

  it.each([
    [403, "You do not have permission to delete this document."],
    [404, "This document is not a Doc Vault upload, or it is already gone."],
    [409, "This document is still being used and cannot be deleted."],
    [500, "The document could not be deleted. Please try again."],
    [502, "The document could not be deleted. Please try again."],
  ])("explains a %i", async (status, message) => {
    reply(status);
    await expect(deleteFromVault(7)).rejects.toThrow(message);
  });

  it.each([
    [500, "the file for document 8 was deleted but its row was not; delete it again to finish"],
    [502, "could not delete the file for document 8; the row is kept"],
  ])("shows the server's own reason for a %i", async (status, detail) => {
    reply(status, { detail });
    await expect(deleteFromVault(8)).rejects.toThrow(detail);
  });

  it("keeps the friendly text for a 409 even when the server sends a detail", async () => {
    reply(409, { detail: "document 8 is still referenced; unlink it first" });
    await expect(deleteFromVault(8)).rejects.toThrow("This document is still being used and cannot be deleted.");
  });

  it("falls back to the generic text when the body is not JSON", async () => {
    fetchMock.mockResolvedValueOnce({ ok: false, status: 500, json: async () => { throw new SyntaxError("not JSON"); } });
    await expect(deleteFromVault(8)).rejects.toThrow("The document could not be deleted. Please try again.");
  });
});
