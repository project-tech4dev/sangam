import { afterEach, describe, expect, it, vi } from "vitest";

const getSession = vi.fn();
vi.mock("@/lib/supabase/client", () => ({ createClient: () => ({ auth: { getSession } }) }));

// DEV_LOGIN is read once at import, so each mode needs a fresh module graph.
async function load(devLogin: boolean) {
  vi.resetModules();
  vi.stubEnv("NEXT_PUBLIC_SUPABASE_URL", devLogin ? "" : "https://x.supabase.co");
  vi.stubEnv("NEXT_PUBLIC_DEV_AUTH", devLogin ? "1" : "");
  return { dev: await import("@/lib/devAuth"), headers: await import("@/lib/api/auth-headers") };
}

afterEach(() => {
  vi.unstubAllEnvs();
  document.cookie = "sangam-dev-as=; path=/; max-age=0";
  getSession.mockReset();
});

describe("dev sign-in", () => {
  it("round-trips the chosen user through a cookie and sends it as a dev bearer", async () => {
    const { dev, headers } = await load(true);
    expect(dev.DEV_LOGIN).toBe(true);
    expect(dev.DEV_USERS).toContain("steward@local.test");
    expect(dev.devEmail()).toBeNull();
    expect(await headers.authHeaders()).toEqual({});
    dev.setDevEmail("admin@local.test");
    expect(dev.devEmail()).toBe("admin@local.test");
    expect(await headers.authHeaders()).toEqual({ Authorization: "Bearer dev:admin@local.test" });
    dev.setDevEmail(null);
    expect(dev.devEmail()).toBeNull();
  });

  it("is off whenever Supabase is configured", async () => {
    const { dev } = await load(false);
    dev.setDevEmail("admin@local.test");
    expect(dev.DEV_LOGIN).toBe(false);
    expect(dev.devEmail()).toBeNull();
  });
});

describe("authHeaders with Supabase", () => {
  it("sends the session's access token, or nothing when signed out", async () => {
    const { headers } = await load(false);
    getSession.mockResolvedValueOnce({ data: { session: { access_token: "jwt" } } });
    expect(await headers.authHeaders()).toEqual({ Authorization: "Bearer jwt" });
    getSession.mockResolvedValueOnce({ data: { session: null } });
    expect(await headers.authHeaders()).toEqual({});
  });
});
