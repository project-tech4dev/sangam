import { afterEach, describe, expect, it, vi } from "vitest";

const exchangeCodeForSession = vi.fn();
vi.mock("@/lib/supabase/server", () => ({
  createClient: async () => ({ auth: { exchangeCodeForSession } }),
}));

const { GET } = await import("@/app/auth/callback/route");

const behindProxy = (path: string) =>
  new Request(`http://0.0.0.0:3000${path}`, {
    headers: { "x-forwarded-host": "app.example.org", "x-forwarded-proto": "https" },
  });

describe("auth callback", () => {
  afterEach(() => exchangeCodeForSession.mockReset());

  it("sends a signed-in person to the next path on the public host", async () => {
    exchangeCodeForSession.mockResolvedValue({ error: null });
    const res = await GET(behindProxy("/auth/callback?code=abc&next=/settings"));
    expect(res.headers.get("location")).toBe("https://app.example.org/settings");
  });

  it("sends a failed sign-in to the error page on the public host, not the container's", async () => {
    const res = await GET(behindProxy("/auth/callback"));
    expect(res.headers.get("location")).toBe("https://app.example.org/auth/error");
  });

  it("uses the request's own origin with no proxy in front", async () => {
    exchangeCodeForSession.mockResolvedValue({ error: new Error("expired") });
    const res = await GET(new Request("https://sangam.example/auth/callback?code=abc"));
    expect(res.headers.get("location")).toBe("https://sangam.example/auth/error");
  });
});
