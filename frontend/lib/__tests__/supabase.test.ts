import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

type CookieAdapter = { getAll(): unknown; setAll(c: { name: string; value: string; options?: object }[]): void };
const getClaims = vi.fn();
const createServerClient = vi.fn((_url: string, _key: string, opts: { cookies: CookieAdapter }) => {
  adapter = opts.cookies;
  return { auth: { getClaims } };
});
const createBrowserClient = vi.fn(() => ({ browser: true }));
let adapter: CookieAdapter;
vi.mock("@supabase/ssr", () => ({ createServerClient, createBrowserClient }));

const cookieStore = { getAll: vi.fn(() => [{ name: "a", value: "1" }]), set: vi.fn() };
vi.mock("next/headers", () => ({ cookies: async () => cookieStore }));

const keys = () => {
  vi.stubEnv("NEXT_PUBLIC_SUPABASE_URL", "https://x.supabase.co");
  vi.stubEnv("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY", "pk");
};

afterEach(() => {
  vi.unstubAllEnvs();
  vi.clearAllMocks();
});

describe("updateSession", () => {
  it("gates nothing when Supabase is not configured", async () => {
    vi.stubEnv("NEXT_PUBLIC_SUPABASE_URL", "");
    const { updateSession } = await import("@/lib/supabase/middleware");
    const res = await updateSession(new NextRequest("http://x/import"));
    expect(res.status).toBe(200);
    expect(createServerClient).not.toHaveBeenCalled();
  });

  it("sends a signed-out visitor to sign in, keeping where they were going", async () => {
    keys();
    getClaims.mockResolvedValue({ data: null });
    const { updateSession } = await import("@/lib/supabase/middleware");
    const res = await updateSession(new NextRequest("http://x/import/runs?id=4"));
    expect(res.status).toBe(307);
    const to = new URL(res.headers.get("location")!);
    expect(to.pathname).toBe("/auth/login");
    expect(to.searchParams.get("next")).toBe("/import/runs?id=4");
  });

  it("lets a signed-out visitor see public pages and a signed-in one see /import", async () => {
    keys();
    const { updateSession } = await import("@/lib/supabase/middleware");
    getClaims.mockResolvedValue({ data: null });
    expect((await updateSession(new NextRequest("http://x/importer"))).status).toBe(200);
    expect((await updateSession(new NextRequest("http://x/ask"))).status).toBe(200);
    getClaims.mockResolvedValue({ data: { claims: { sub: "u" } } });
    expect((await updateSession(new NextRequest("http://x/import"))).status).toBe(200);
  });

  it("copies refreshed session cookies onto the response", async () => {
    keys();
    getClaims.mockImplementation(async () => {
      adapter.setAll([{ name: "sb-token", value: "new", options: { path: "/" } }]);
      return { data: { claims: { sub: "u" } } };
    });
    const { updateSession } = await import("@/lib/supabase/middleware");
    const req = new NextRequest("http://x/ask", { headers: { cookie: "sb-token=old" } });
    const res = await updateSession(req);
    expect(adapter.getAll()).toEqual([{ name: "sb-token", value: "new" }]);
    expect(res.cookies.get("sb-token")?.value).toBe("new");
  });
});

describe("Supabase clients", () => {
  it("build from the public env keys", async () => {
    keys();
    const { createClient } = await import("@/lib/supabase/client");
    expect(createClient()).toEqual({ browser: true });
    expect(createBrowserClient).toHaveBeenCalledWith("https://x.supabase.co", "pk");
  });

  it("the server client reads cookies and tolerates a write from a server component", async () => {
    keys();
    const { createClient } = await import("@/lib/supabase/server");
    await createClient();
    expect(adapter.getAll()).toEqual([{ name: "a", value: "1" }]);
    adapter.setAll([{ name: "b", value: "2", options: {} }]);
    expect(cookieStore.set).toHaveBeenCalledWith("b", "2", {});
    cookieStore.set.mockImplementationOnce(() => {
      throw new Error("read-only");
    });
    expect(() => adapter.setAll([{ name: "c", value: "3" }])).not.toThrow();
  });
});

describe("cn", () => {
  it("merges conflicting Tailwind classes, last wins", async () => {
    const { cn } = await import("@/lib/utils");
    expect(cn("px-2 text-sm", false && "hidden", "px-4")).toBe("text-sm px-4");
  });
});
