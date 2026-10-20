import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import type { RegistryIndex } from "@/features/ask/lib/citations";
import type { TraceStep, Turn } from "@/lib/useAgentChat";

const chat = vi.hoisted(() => ({
  state: { turns: [] as Turn[], isRunning: false, isReady: true, isLoadingHistory: false },
  send: vi.fn(),
  args: [] as unknown[],
}));
vi.mock("@/features/ask/lib/useSangamChat", () => ({
  useSangamChat: (...args: unknown[]) => ((chat.args = args), { send: chat.send, ...chat.state }),
}));
const saveThread = vi.fn();
vi.mock("@/features/ask/lib/threads", async (original) => ({
  ...(await original<typeof import("@/features/ask/lib/threads")>()),
  saveThread: (t: unknown) => saveThread(t),
}));

import { AnswerCard, CitationChip } from "@/features/ask/components/AnswerCard";
import { ChatPane } from "@/features/ask/components/ChatPane";
import { EvidenceRail } from "@/features/ask/components/EvidenceRail";
import { Sidebar } from "@/features/ask/components/Sidebar";
import { TraceCard } from "@/features/ask/components/TraceCard";

beforeAll(() => {
  Element.prototype.scrollIntoView = vi.fn();
});
afterEach(() => {
  vi.clearAllMocks();
  chat.state = { turns: [], isRunning: false, isReady: true, isLoadingHistory: false };
});

const index: RegistryIndex = {
  orgs: new Map([[1, { slug: "kabil", name: "KABIL", sourceUrl: "https://kabil.example/about", sourceName: "KABIL site", fetchedAt: "2026-09-01T10:00:00Z" }]]),
  funders: new Map([[2, { slug: "axis-bank-foundation", name: "Axis Bank Foundation" }]]),
  scores: new Map([[3, { funderSlug: "axis-bank-foundation", orgName: "KABIL", funderName: "Axis", rubricVersion: "v1" }]]),
  activities: new Map(),
};
const step = (id: string, tool: string, args: unknown = {}, result: string | null = "", running = false): TraceStep => ({ id, tool, args, result, running });

describe("AnswerCard", () => {
  it("renders markdown with citation chips linked into the Registry", () => {
    render(<AnswerCard answer={"KABIL [org:1] fits Axis [funder:2]. See [score:9], [news:4] and [docs](https://x.example)\n\n| a |\n|---|\n| 1 |"} index={index} />);
    expect(screen.getByRole("link", { name: "org:1" })).toHaveAttribute("href", "/registry/kabil");
    expect(screen.getByRole("link", { name: "funder:2" })).toHaveAttribute("href", "/registry/funders/axis-bank-foundation");
    expect(screen.getByText("score:9")).toHaveAttribute("title", "score #9 — score evidence in the base");
    expect(screen.getByRole("link", { name: "docs" })).toHaveAttribute("target", "_blank");
    expect(screen.getByRole("table")).toBeInTheDocument();
  });

  it("shows a source in words when given them, and nothing for a malformed link", () => {
    render(<AnswerCard answer="Fits [org:1]." index={null} words={{ org: "Organisation's record" }} />);
    expect(screen.getByRole("link", { name: "Organisation's record" })).toHaveAttribute("href", "/registry/1");
    const { container } = render(<CitationChip href="sangam://bad" index={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("TraceCard", () => {
  const steps = [step("1", "db_query", { purpose: "Count orgs" }), step("2", "db_list_tables", {}, null, true)];

  it("folds finished steps behind a toggle", async () => {
    render(<TraceCard steps={steps} streaming={false} />);
    expect(screen.getByText("How this answer was made — 2 steps")).toBeInTheDocument();
    expect(screen.queryByText("Count orgs")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Show steps" }));
    expect(screen.getByText("Count orgs")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Hide steps" }));
    expect(screen.queryByText("Count orgs")).toBeNull();
  });

  it("shows every step while streaming, and nothing with no steps", () => {
    const { container, rerender } = render(<TraceCard steps={steps.slice(0, 1)} streaming />);
    expect(screen.getByText("Working…")).toBeInTheDocument();
    expect(screen.getByText("Count orgs")).toBeInTheDocument();
    rerender(<TraceCard steps={[]} streaming={false} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("EvidenceRail", () => {
  it("shows what is in the base before any question", () => {
    render(<EvidenceRail latest={null} stats={{ orgs: 12 }} index={index} />);
    expect(screen.getByText("What's in the base")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });

  it("lists the phases, sources and SQL behind an answer", async () => {
    const result = ["2 row(s). tables: orgs, grants.", "executed: SELECT * FROM orgs", "sources: 1", "  orgs · https://darpan.example/1 · Darpan · 2026-08-01"].join("\n");
    const latest: Turn = {
      id: "t",
      question: "q",
      answer: "KABIL [org:1] scores [score:3].",
      streaming: true,
      steps: [
        step("a", "db_describe_table", { tables: "orgs, grants" }),
        step("b", "db_query", { purpose: "Find KABIL" }, result),
        step("c", "db_query", { sql: "SELECT count(*) FROM grants" }, "1 row(s). tables: grants.\nsources: none — aggregated", true),
      ],
    };
    render(<EvidenceRail latest={latest} stats={null} index={index} />);
    expect(screen.getByText("Reading the table structure")).toBeInTheDocument();
    expect(screen.getByText("orgs, grants")).toBeInTheDocument();
    expect(screen.getByText("· 2")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "darpan.example" })).toHaveAttribute("href", "https://darpan.example/1");
    expect(screen.getByRole("link", { name: "kabil.example" })).toBeInTheDocument();
    expect(screen.getByText("Sangam rubric v1")).toBeInTheDocument();
    expect(screen.getByText(/Some rows carry no source of their own: aggregated\. Read from orgs, grants\./)).toBeInTheDocument();
    await userEvent.click(screen.getByText("Query 1 of 2"));
    expect(screen.getByText("SELECT * FROM orgs")).toBeInTheDocument();
    expect(screen.getByText("SELECT count(*) FROM grants")).toBeInTheDocument();
    expect(screen.queryByText("What's in the base")).toBeNull();
  });

  it("counts sources past the limit and names tables with no source", () => {
    const many = Array.from({ length: 12 }, (_, i) => `  orgs · https://s${i}.example/ · S${i}`).join("\n");
    const latest: Turn = { id: "t", question: "q", answer: "", streaming: false, steps: [step("a", "db_query", {}, `sources: 12\n${many}`)] };
    const { unmount } = render(<EvidenceRail latest={latest} stats={null} index={null} />);
    expect(screen.getByText("…and 2 more source(s) behind this answer.")).toBeInTheDocument();
    unmount();
    const bare: Turn = { ...latest, steps: [step("a", "db_query", {}, "3 row(s). tables: funders.")] };
    render(<EvidenceRail latest={bare} stats={null} index={null} />);
    expect(screen.getByText("Read from funders; no source URL is recorded for those rows.")).toBeInTheDocument();
  });
});

describe("Sidebar", () => {
  const threads = Array.from({ length: 7 }, (_, i) => ({ id: `t${i}`, title: `Chat ${i}`, createdAt: i }));
  const props = () => ({
    collapsed: false, onToggle: vi.fn(), view: "ask" as const, onView: vi.fn(), threads, activeThread: "t1",
    onPickThread: vi.fn(), onNewChat: vi.fn(), counts: { proposals: 3 }, canScout: true,
  });

  it("lists the five latest chats and opens one, or all of them", async () => {
    const p = props();
    render(<Sidebar {...p} />);
    expect(screen.getAllByRole("button", { name: /^Chat \d$/ })).toHaveLength(5);
    expect(screen.getByRole("button", { name: "Chat 1" })).toHaveAttribute("data-active", "true");
    await userEvent.click(screen.getByRole("button", { name: "Chat 3" }));
    expect(p.onPickThread).toHaveBeenCalledWith("t3");
    await userEvent.click(screen.getByRole("button", { name: "Show All 7 Chats →" }));
    expect(p.onView).toHaveBeenCalledWith("chats");
    await userEvent.click(screen.getByRole("button", { name: "+ New Chat" }));
    expect(p.onNewChat).toHaveBeenCalled();
  });

  it("opens a use case, shows the proposal count and Scout under Tools", async () => {
    const p = props();
    render(<Sidebar {...p} />);
    await userEvent.click(screen.getByRole("button", { name: "Funder Match" }));
    expect(p.onView).toHaveBeenCalledWith("funder-match");
    expect(screen.getByRole("button", { name: /^Proposals\s*3$/ })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Sangam Scout" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Tools" }));
    expect(screen.getByRole("link", { name: "Sangam Scout" })).toHaveAttribute("href", "/import");
    await userEvent.click(screen.getByRole("button", { name: "Use Cases" }));
    expect(screen.queryByRole("button", { name: "Funder Match" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Collapse Workspace" }));
    expect(p.onToggle).toHaveBeenCalled();
  });

  it("says when there are no chats, and hides Tools from others", () => {
    render(<Sidebar {...props()} threads={[]} canScout={false} />);
    expect(screen.getByText("No past conversations yet.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Tools" })).toBeNull();
  });

  it("collapses to icons that open the workspace at a section", async () => {
    const p = props();
    const { rerender } = render(<Sidebar {...p} collapsed />);
    await userEvent.click(screen.getByRole("button", { name: "New Chat" }));
    expect(p.onNewChat).toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Tools" }));
    expect(p.onToggle).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole("button", { name: "Open Workspace" }));
    expect(p.onToggle).toHaveBeenCalledTimes(2);
    rerender(<Sidebar {...p} collapsed={false} />);
    expect(screen.getByRole("link", { name: "Sangam Scout" })).toBeInTheDocument();
    rerender(<Sidebar {...p} collapsed canScout={false} />);
    await userEvent.click(screen.getByRole("button", { name: "Recent Chats" }));
    expect(screen.queryByRole("button", { name: "Tools" })).toBeNull();
  });
});

describe("ChatPane", () => {
  const props = () => ({ threadId: "th-1", resume: false, seed: null, onFirstSend: vi.fn(), index, onLatestTurn: vi.fn() });

  it("greets a new chat and sends a suggestion, naming the chat once", async () => {
    const p = props();
    render(<ChatPane {...p} />);
    expect(screen.getByRole("heading", { name: "What do you want to know?" })).toBeInTheDocument();
    expect(p.onLatestTurn).toHaveBeenCalledWith(null);
    await userEvent.click(screen.getByRole("button", { name: "What grants has KABIL received?" }));
    expect(chat.send).toHaveBeenCalledWith("What grants has KABIL received?");
    expect(saveThread).toHaveBeenCalledWith(expect.objectContaining({ id: "th-1", title: "What grants has KABIL received?" }));
    expect(p.onFirstSend).toHaveBeenCalledOnce();
    await userEvent.type(screen.getByRole("textbox"), "Next{Meta>}{Enter}{/Meta}");
    expect(chat.send).toHaveBeenCalledWith("Next");
    expect(p.onFirstSend).toHaveBeenCalledOnce();
  });

  it("prefills a seed without sending it", async () => {
    render(<ChatPane {...props()} seed="Help me decide" />);
    expect(screen.getByRole("textbox")).toHaveValue("Help me decide");
    await userEvent.click(screen.getByRole("button", { name: "Ask Sangam" }));
    expect(chat.send).toHaveBeenCalledWith("Help me decide");
  });

  it("shows the turns of a resumed chat and reports the latest", () => {
    const turn: Turn = { id: "x", question: "Who works in Assam?", steps: [], answer: "KABIL [org:1].", streaming: false };
    chat.state.turns = [turn];
    const p = { ...props(), resume: true };
    render(<ChatPane {...p} />);
    expect(chat.args).toEqual(["th-1", true]);
    expect(screen.getByText("Who works in Assam?")).toBeInTheDocument();
    expect(within(screen.getByText("KABIL", { exact: false }).closest(".answer-md")!).getByRole("link")).toHaveAttribute("href", "/registry/kabil");
    expect(p.onLatestTurn).toHaveBeenCalledWith(turn);
  });

  it("says what it is waiting for", () => {
    chat.state = { ...chat.state, isReady: false };
    const { rerender } = render(<ChatPane {...props()} />);
    expect(screen.getByText("Connecting to the agent…")).toBeInTheDocument();
    chat.state = { ...chat.state, isReady: true, isLoadingHistory: true };
    rerender(<ChatPane {...props()} />);
    expect(screen.getByText("Loading this chat…")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "What do you want to know?" })).toBeNull();
    chat.state = { ...chat.state, isLoadingHistory: false, isRunning: true };
    rerender(<ChatPane {...props()} />);
    expect(screen.getByRole("button", { name: "Working…" })).toBeDisabled();
  });
});
