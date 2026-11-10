import { afterEach, describe, expect, it, vi } from "vitest";

const cookieGet = vi.fn();
const getSession = vi.fn();
vi.mock("next/headers", () => ({ cookies: async () => ({ get: cookieGet, getAll: () => [] }) }));
vi.mock("@/lib/supabase/server", () => ({ createClient: async () => ({ auth: { getSession } }) }));

async function load(devLogin: boolean) {
  vi.resetModules();
  vi.stubEnv("NEXT_PUBLIC_SUPABASE_URL", devLogin ? "" : "https://x.supabase.co");
  vi.stubEnv("NEXT_PUBLIC_DEV_AUTH", devLogin ? "1" : "");
  return (await import("@/lib/api/auth-headers.server")).serverAuthHeaders;
}

afterEach(() => {
  vi.unstubAllEnvs();
  cookieGet.mockReset();
  getSession.mockReset();
});

describe("serverAuthHeaders", () => {
  it("reads the dev cookie in dev sign-in", async () => {
    const headers = await load(true);
    cookieGet.mockReturnValueOnce({ value: "member@local.test" });
    expect(await headers()).toEqual({ Authorization: "Bearer dev:member@local.test" });
    cookieGet.mockReturnValueOnce(undefined);
    expect(await headers()).toEqual({});
  });

  it("forwards the Supabase session token", async () => {
    const headers = await load(false);
    getSession.mockResolvedValueOnce({ data: { session: { access_token: "jwt" } } });
    expect(await headers()).toEqual({ Authorization: "Bearer jwt" });
    getSession.mockResolvedValueOnce({ data: { session: null } });
    expect(await headers()).toEqual({});
  });
});
