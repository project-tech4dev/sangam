import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect, useState, type ComponentType, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { navigation } from "@/tests/setup";
import { review, source, status, stubFetch } from "../components/__tests__/fakes";

type ChatProps = {
  threadId: string;
  resume: boolean;
  onStartOver: () => void;
  onFirstSend: (text: string) => void;
  below: ReactNode;
  access: { staff: boolean };
  vaultFiles?: unknown[];
  staff: unknown;
};
const seen = vi.hoisted(() => ({ chat: null as ChatProps | null, view: null as Record<string, unknown> | null, threads: vi.fn() }));

vi.mock("../ScoutChat", () => ({
  ScoutChat: (p: ChatProps) => {
    seen.chat = p;
    return <div data-testid="chat">{p.below}</div>;
  },
}));
vi.mock("@/lib/api/auth-headers", () => ({ authHeaders: async () => ({}) }));

import { ImportView } from "../ImportView";

const overview = (staff: boolean) => ({
  me: { is_staff: staff, memberships: [{ org_slug: "a", org_name: "Org A", role: "steward" }] },
  research: [
    {
      id: 1, entity_name: "KABIL", canonical_name: null, entity_kind: "funder", slug: "kabil", status: "ready", stopped_reason: null,
      summary: "", fact_count: 3, sources_read: [], not_found: [], researched_at: "2026-10-01T00:00:00Z", saved_at: null,
      resolved_org_id: null, resolved_funder_id: null,
    },
  ],
  vault: [{ id: 5, title: "Report", doc_type: "pdf", org: "a", org_id: 10, org_name: "Org A" }],
  sources: [source()],
  runs: [],
  queue: [],
  proposals: [],
});

beforeEach(() => {
  seen.chat = null;
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("ImportView", () => {
  const props = { threadId: "import-1", resume: false, onStartOver: vi.fn(), onFirstSend: vi.fn() };

  it("gives a steward their access and files, and no team tools", async () => {
    stubFetch({ "/api/ingest/overview": overview(false) });
    render(<ImportView {...props} />);
    expect(seen.chat!.access).toEqual({ staff: false, stewardOf: [], orgs: [] });
    expect(await screen.findByText("Researched recently")).toBeInTheDocument();
    expect(seen.chat!.access).toEqual({ staff: false, stewardOf: ["Org A"], orgs: [{ slug: "a", name: "Org A" }] });
    expect(seen.chat!.vaultFiles).toEqual([{ id: 5, title: "Report", doc_type: "pdf", org: "a", orgId: 10, orgName: "Org A" }]);
    expect(seen.chat!.staff).toBeNull();
    expect(screen.queryByText("Team tools")).not.toBeInTheDocument();
  });

  it("gives staff the team tools and the staff panels", async () => {
    stubFetch({ "/api/ingest/overview": overview(true) });
    render(<ImportView {...props} />);
    expect(await screen.findByText("Team tools")).toBeInTheDocument();
    expect(seen.chat!.staff).toMatchObject({ sources: [source()], runs: [] });
    expect(screen.getByText("Which websites is Sangam allowed to read?")).toBeInTheDocument();
  });

  it("says when the overview fails", async () => {
    stubFetch({ "/api/ingest/overview": status(503) });
    render(<ImportView {...props} />);
    expect(await screen.findByText("Could not load what was researched: GET /api/ingest/overview failed: 503")).toBeInTheDocument();
  });

  it("reloads only the research list after a change", async () => {
    let deleted = false;
    const fetchMock = stubFetch({
      "/api/ingest/overview": overview(true),
      "/api/ingest/research?limit=25": () => (deleted ? [] : status(500)),
      "/research/kabil": () => {
        deleted = true;
        return { ok: true };
      },
      "/review": review(),
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<ImportView {...props} />);
    await userEvent.click(await screen.findByRole("button", { name: "Delete" }));
    await waitFor(() => expect(screen.queryByText("Researched recently")).not.toBeInTheDocument());
    expect(fetchMock.mock.calls.filter(([u]) => String(u).includes("/overview"))).toHaveLength(1);
  });
});

describe("ImportPage", () => {
  beforeEach(() => {
    vi.resetModules();
    seen.threads.mockReset();
    seen.view = null;
    vi.doMock("@/lib/AgentProviders", () => ({ AgentProviders: ({ children }: { children: ReactNode }) => <>{children}</> }));
    vi.doMock("../ImportView", () => ({
      ImportView: (p: Record<string, unknown>) => {
        seen.view = p;
        return <p>view {String(p.threadId)}</p>;
      },
    }));
    vi.doMock("../lib/threads", async (orig) => ({ ...(await orig<object>()), fetchImportThreads: () => seen.threads() }));
    vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: false })));
  });

  const thread = "import-00000000-0000-0000-0000-000000000001";

  it("lists past chats and opens the one in the address", async () => {
    navigation.search = new URLSearchParams({ thread });
    seen.threads.mockResolvedValue([{ id: thread, title: "KABIL funding", createdAt: Date.parse("2026-10-05") }]);
    const { ImportPage } = await import("../ImportPage");
    render(<ImportPage />);
    expect(await screen.findByRole("button", { name: /KABIL funding/ })).toHaveAttribute("aria-current", "page");
    expect(seen.view).toMatchObject({ threadId: thread, resume: true });
  });

  it("says when the list fails, and starts a new chat", async () => {
    seen.threads.mockRejectedValue(new Error("down"));
    const push = vi.spyOn(window.history, "pushState");
    const { ImportPage } = await import("../ImportPage");
    render(<ImportPage />);
    expect(await screen.findByText("Couldn't load past imports.")).toBeInTheDocument();
    expect(seen.view).toMatchObject({ resume: false });
    await userEvent.click(screen.getByRole("button", { name: "+ New chat" }));
    expect(screen.getByText(/^view import-/)).toBeInTheDocument();
    // A bare /import already has no thread, so nothing is pushed.
    expect(push).not.toHaveBeenCalled();
  });

  it("lists a new chat on its first send and refreshes the list later", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    seen.threads.mockResolvedValue([]);
    const { ImportPage } = await import("../ImportPage");
    render(<ImportPage />);
    expect(await screen.findByText("No past chats yet.")).toBeInTheDocument();
    act(() => (seen.view!.onFirstSend as (t: string) => void)("Funding profile for KABIL"));
    expect(screen.getByRole("button", { name: /Funding profile for KABIL/ })).toBeInTheDocument();
    await act(async () => vi.advanceTimersByTime(3000));
    expect(seen.threads).toHaveBeenCalledTimes(2);
    // The list keeps the chat it just started while the server has not titled it yet.
    expect(screen.getByRole("button", { name: /Funding profile for KABIL/ })).toBeInTheDocument();
    vi.useRealTimers();
  });

  it("closes the list on a phone after a pick", async () => {
    (globalThis.matchMedia as unknown as ReturnType<typeof vi.fn>).mockReturnValue({ matches: true });
    seen.threads.mockResolvedValue([{ id: thread, title: "Old", createdAt: Date.now() }]);
    const { ImportPage } = await import("../ImportPage");
    render(<ImportPage />);
    // Phones start collapsed.
    await userEvent.click(screen.getByRole("button", { name: "Show past chats" }));
    await userEvent.click(await screen.findByRole("button", { name: /Old/ }));
    expect(screen.getByRole("button", { name: "Show past chats" })).toBeInTheDocument();
    act(() => (seen.view!.onStartOver as () => void)());
  });
});

describe("ImportLoader", () => {
  it("shows a placeholder, then the page once its code arrives", async () => {
    vi.resetModules();
    vi.doMock("next/dynamic", () => ({
      default: (load: () => Promise<ComponentType>, opts: { loading: () => ReactNode }) =>
        function Dynamic() {
          const [Page, setPage] = useState<ComponentType | null>(null);
          useEffect(() => void load().then((c) => setPage(() => c)), []);
          return Page ? <Page /> : <>{opts.loading()}</>;
        },
    }));
    vi.doMock("../ImportPage", () => ({ ImportPage: () => <p>Scout page</p> }));
    const { ImportLoader } = await import("../ImportLoader");
    render(<ImportLoader />);
    expect(screen.getByText("Opening Scout…")).toBeInTheDocument();
    expect(await screen.findByText("Scout page")).toBeInTheDocument();
  });
});
