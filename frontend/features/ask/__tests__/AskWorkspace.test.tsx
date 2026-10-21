import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { navigation } from "@/tests/setup";

const setUrlParams = vi.fn();
vi.mock("@/lib/url", async (original) => ({
  ...(await original<typeof import("@/lib/url")>()),
  setUrlParams: (...a: unknown[]) => setUrlParams(...a),
}));
const threads = vi.hoisted(() => ({ fetch: vi.fn(), load: vi.fn(() => [] as unknown[]) }));
vi.mock("@/features/ask/lib/threads", () => ({ fetchThreads: (id: string) => threads.fetch(id), loadThreads: () => threads.load() }));
const pending = vi.hoisted(() => ({ value: null as string | null }));
vi.mock("@/features/ask/lib/pendingQuestion", () => ({ takePendingQuestion: () => pending.value }));
vi.mock("@/features/ask/views/proposals/api", () => ({ useProposals: () => [{ id: 1 }, { id: 2 }] }));

// Each screen is tested on its own; here a stub shows which one is up and exposes its callbacks.
type Props = Record<string, unknown>;
const seen: Record<string, Props> = {};
const stub = (name: string, act?: (p: Props) => ReactNode) =>
  function Stub(p: Props) {
    seen[name] = p;
    return (
      <section aria-label={name}>
        {name}
        {act?.(p)}
      </section>
    );
  };
const button = (label: string, fn: () => void) => (
  <button type="button" onClick={fn}>
    {label}
  </button>
);
vi.mock("@/features/ask/components/ChatPane", () => ({
  ChatPane: (p: Props) => stub("ChatPane", (p) => (
    <>
      <span>{`seed:${p.seed ?? ""} resume:${p.resume}`}</span>
      {button("first send", p.onFirstSend as () => void)}
      {button("report turn", () => (p.onLatestTurn as (t: unknown) => void)({ id: "t" }))}
    </>
  ))(p),
}));
vi.mock("@/features/ask/components/EvidenceRail", () => ({
  EvidenceRail: (p: Props) => stub("EvidenceRail", (p) => <span>{p.latest ? "has turn" : "no turn"}</span>)(p),
}));
vi.mock("@/features/ask/views/VaultView", () => ({
  VaultView: (p: Props) => stub("VaultView")(p),
}));
vi.mock("@/features/ask/views/media/MediaView", () => ({
  MediaView: (p: Props) => stub("MediaView")(p),
}));
vi.mock("@/features/ask/views/ChatsView", () => ({
  ChatsView: (p: Props) => stub("ChatsView", (p) => button("pick chat", () => (p.onPick as (id: string) => void)("11111111-1111-1111-1111-111111111111")))(p),
}));
vi.mock("@/features/ask/views/FunderMatchView", () => ({
  FunderMatchView: (p: Props) => stub("FunderMatchView", (p) => {
    const nav = p.nav as { open: (id: number) => void; list: (id: number) => void };
    return (
      <>
        {button("open proposal", () => nav.open(4))}
        {button("list proposals", () => nav.list(9))}
      </>
    );
  })(p),
}));
vi.mock("@/features/ask/views/ProposalsView", () => ({
  ProposalsView: (p: Props) => stub("ProposalsView", (p) => (
    <>
      <span>{`open:${p.open} funder:${p.funder}`}</span>
      {button("back to list", () => (p.onOpen as (id: number | null) => void)(null))}
      {button("open 5", () => (p.onOpen as (id: number | null) => void)(5))}
      {button("to funder match", p.onFunderMatch as () => void)}
    </>
  ))(p),
}));
vi.mock("@/features/ask/views/RfpWatchView", () => ({
  RfpWatchView: (p: Props) => stub("RfpWatchView", (p) => (
    <>
      {button("ask about call", () => (p.onAsk as (q: string) => void)("Should we apply?"))}
      {button("rfp to funder match", p.onFunderMatch as () => void)}
    </>
  ))(p),
}));

import { AskWorkspace, type IndexPayload } from "@/features/ask/AskWorkspace";

const payload: IndexPayload = {
  orgs: [{ id: 1, slug: "kabil", name: "KABIL", sourceUrl: null, sourceName: null, fetchedAt: null }],
  funders: [],
  scores: [],
  activities: [],
  stats: { orgs: 1 },
  canScout: false,
  me: null,
};
const at = (query: string) => (navigation.search = new URLSearchParams(query));

beforeEach(() => {
  window.matchMedia = vi.fn(() => ({ matches: false }) as MediaQueryList);
  threads.fetch.mockResolvedValue([{ id: "a", title: "Saved chat", createdAt: 1 }]);
  pending.value = null;
});
afterEach(() => vi.clearAllMocks());

describe("AskWorkspace", () => {
  it("opens a new chat with the server's chat list and the evidence rail", async () => {
    render(<AskWorkspace payload={payload} />);
    expect(screen.getByRole("region", { name: "ChatPane" })).toHaveTextContent("seed: resume:false");
    expect(await screen.findByRole("button", { name: "Saved chat" })).toBeInTheDocument();
    expect(setUrlParams).toHaveBeenCalledWith({ q: null }, "replace");
    expect(screen.getByRole("region", { name: "EvidenceRail" })).toHaveTextContent("no turn");
    await userEvent.click(screen.getByRole("button", { name: "report turn" }));
    expect(screen.getByRole("region", { name: "EvidenceRail" })).toHaveTextContent("has turn");
    await userEvent.click(screen.getByRole("button", { name: "first send" }));
    expect(setUrlParams).toHaveBeenCalledWith({ thread: expect.any(String) }, "replace");
    expect(threads.fetch).toHaveBeenCalledTimes(2);
  });

  it("falls back to this browser's chats when the server cannot answer", async () => {
    threads.fetch.mockRejectedValue(new Error("offline"));
    threads.load.mockReturnValue([{ id: "b", title: "Local chat", createdAt: 1 }]);
    render(<AskWorkspace payload={payload} />);
    expect(await screen.findByRole("button", { name: "Local chat" })).toBeInTheDocument();
  });

  it("prefills a question from the preview or the address in a fresh chat", () => {
    pending.value = "From the preview";
    const { unmount } = render(<AskWorkspace payload={payload} initialQuestion="From q" />);
    expect(screen.getByRole("region", { name: "ChatPane" })).toHaveTextContent("seed:From the preview");
    expect(setUrlParams).toHaveBeenCalledWith({ q: null, thread: null }, "replace");
    unmount();
    pending.value = null;
    render(<AskWorkspace payload={payload} initialQuestion="From q" />);
    expect(screen.getByRole("region", { name: "ChatPane" })).toHaveTextContent("seed:From q");
  });

  it("collapses the rail on a phone", () => {
    window.matchMedia = vi.fn(() => ({ matches: true }) as MediaQueryList);
    render(<AskWorkspace payload={payload} />);
    expect(screen.getByRole("button", { name: "Open Workspace" })).toBeInTheDocument();
  });

  it("switches screens from the sidebar and starts a new chat", async () => {
    render(<AskWorkspace payload={payload} />);
    await userEvent.click(screen.getByRole("button", { name: "Media & Signals" }));
    expect(setUrlParams).toHaveBeenCalledWith({ view: "media", proposal: null, funder: null, org: null });
    setUrlParams.mockClear();
    await userEvent.click(screen.getByRole("button", { name: "Funder Match" }));
    await userEvent.click(screen.getByRole("button", { name: "+ New Chat" }));
    expect(setUrlParams).toHaveBeenLastCalledWith({ view: null, proposal: null, funder: null, org: null, thread: null });
    await userEvent.click(screen.getByRole("button", { name: "Collapse Workspace" }));
    expect(screen.getByRole("button", { name: "Open Workspace" })).toBeInTheDocument();
  });

  it("does not rewrite the address for the screen already open", async () => {
    at("view=vault");
    render(<AskWorkspace payload={payload} />);
    expect(screen.getByRole("region", { name: "VaultView" })).toBeInTheDocument();
    setUrlParams.mockClear();
    await userEvent.click(screen.getByRole("button", { name: "Doc Vault" }));
    expect(setUrlParams).not.toHaveBeenCalled();
  });

  it("hands the page's /api/me to each screen that picks an organisation", () => {
    const me = { id: "u", email: null, is_staff: false, is_anonymous: false, memberships: [] };
    for (const [view, name] of [["funder-match", "FunderMatchView"], ["rfpwatch", "RfpWatchView"], ["media", "MediaView"]]) {
      at(`view=${view}`);
      const { unmount } = render(<AskWorkspace payload={{ ...payload, me }} />);
      expect(seen[name].me).toBe(me);
      unmount();
    }
  });

  it("shows Media & Signals and All Chats, and opens a picked chat", async () => {
    at("view=media");
    const { unmount } = render(<AskWorkspace payload={payload} />);
    expect(screen.getByRole("region", { name: "MediaView" })).toBeInTheDocument();
    unmount();
    at("view=chats");
    render(<AskWorkspace payload={payload} />);
    await userEvent.click(screen.getByRole("button", { name: "pick chat" }));
    expect(setUrlParams).toHaveBeenCalledWith({ view: null, proposal: null, funder: null, org: null, thread: "11111111-1111-1111-1111-111111111111" });
  });

  it("opens a proposal, or the list for a funder, from Funder Match", async () => {
    at("view=funder-match");
    render(<AskWorkspace payload={payload} />);
    await userEvent.click(screen.getByRole("button", { name: "open proposal" }));
    expect(setUrlParams).toHaveBeenCalledWith({ view: "proposals", proposal: "4", funder: null });
    await userEvent.click(screen.getByRole("button", { name: "list proposals" }));
    expect(setUrlParams).toHaveBeenCalledWith({ view: "proposals", proposal: null, funder: "9" });
  });

  it("reads the open proposal from the address and moves between them", async () => {
    at("view=proposals&proposal=5&funder=9");
    render(<AskWorkspace payload={payload} />);
    expect(screen.getByRole("region", { name: "ProposalsView" })).toHaveTextContent("open:5 funder:9");
    expect(screen.getByRole("button", { name: /^Proposals\s*2$/ })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "back to list" }));
    expect(setUrlParams).toHaveBeenCalledWith({ proposal: null });
    await userEvent.click(screen.getByRole("button", { name: "open 5" }));
    expect(setUrlParams).toHaveBeenCalledWith({ proposal: "5" });
    await userEvent.click(screen.getByRole("button", { name: "to funder match" }));
    expect(setUrlParams).toHaveBeenCalledWith({ view: "funder-match", proposal: null, funder: null, org: null });
    // Inside one proposal, Proposals in the sidebar goes back to the list.
    setUrlParams.mockClear();
    await userEvent.click(screen.getByRole("button", { name: /^Proposals\s*2$/ }));
    expect(setUrlParams).toHaveBeenCalledWith({ view: "proposals", proposal: null, funder: null, org: null });
  });

  it("asks about an RFP in a new chat, seeded", async () => {
    at("view=rfpwatch");
    render(<AskWorkspace payload={payload} />);
    await userEvent.click(screen.getByRole("button", { name: "rfp to funder match" }));
    expect(setUrlParams).toHaveBeenCalledWith({ view: "funder-match", proposal: null, funder: null, org: null });
    await userEvent.click(screen.getByRole("button", { name: "ask about call" }));
    expect(setUrlParams).toHaveBeenLastCalledWith({ view: null, proposal: null, funder: null, org: null, thread: null });
    await waitFor(() => expect(threads.fetch).toHaveBeenCalled());
  });
});
