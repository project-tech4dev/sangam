import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SettingsPage } from "@/features/settings/SettingsPage";
import { apiGet } from "@/lib/api";
import { createClient } from "@/lib/supabase/server";

vi.mock("@/lib/api", () => ({ apiGet: vi.fn() }));
vi.mock("@/lib/supabase/server", () => ({ createClient: vi.fn() }));

const get = vi.mocked(apiGet);
const signedIn = (user: object | null) =>
  vi.mocked(createClient).mockResolvedValue({ auth: { getUser: async () => ({ data: { user } }) } } as never);

// Answers each API path from a table, so the order of the parallel calls does not matter.
const api = (routes: Record<string, unknown>) =>
  get.mockImplementation(async (path: string) => {
    if (!(path in routes)) throw new Error(`unexpected ${path}`);
    const value = routes[path];
    if (value instanceof Error) throw value;
    return value as never;
  });

beforeEach(() => {
  get.mockReset();
});

const user = { email: "asha@k.org", user_metadata: { full_name: "Asha" } };

describe("SettingsPage", () => {
  it("asks a signed-out visitor to sign in", async () => {
    signedIn(null);
    api({ "/api/me": new Error("401") });
    render(await SettingsPage());
    expect(screen.getByText("Sign in to see your settings.")).toBeInTheDocument();
    expect(screen.queryByText("Account")).not.toBeInTheDocument();
  });

  it("shows a member's account and organisations, with a members card for each org they admin", async () => {
    signedIn(user);
    api({
      "/api/me": { id: "u1", is_staff: false, memberships: [
        { org_id: 7, org_name: "KABIL", role: "admin" }, { org_id: 8, org_name: "Seva", role: "member" },
      ] },
      "/api/orgs/7/members": [{ user_id: "u1", display_name: "Asha", email: "asha@k.org", role: "admin" }],
    });
    render(await SettingsPage());
    expect(screen.getByText("Asha", { selector: "dd" })).toBeInTheDocument();
    expect(screen.getByText("Seva")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Members of KABIL" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Members of Seva" })).not.toBeInTheDocument();
    expect(get).not.toHaveBeenCalledWith("/api/orgs");
  });

  it("tells a user with no organisation so", async () => {
    signedIn({ email: "new@x.org", user_metadata: {} });
    api({ "/api/me": { id: "u3", is_staff: false, memberships: [] } });
    render(await SettingsPage());
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.getByText("You don't belong to any organisation yet.")).toBeInTheDocument();
  });

  it("gives staff the organisation picker instead of their own list", async () => {
    signedIn(user);
    api({ "/api/me": { id: "s1", is_staff: true, memberships: [] }, "/api/orgs": [{ id: 7, name: "KABIL", slug: "kabil" }] });
    render(await SettingsPage());
    expect(screen.queryByText("My organisations")).not.toBeInTheDocument();
    expect(screen.getByRole("option", { name: "KABIL" })).toBeInTheDocument();
  });
});
