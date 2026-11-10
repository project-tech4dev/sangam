import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import type { Turn } from "@/lib/useAgentChat";
import { proposal } from "./fixtures";

type Interrupt = { enabled: (e: { value: unknown }) => boolean; render: (a: { event: { value: unknown }; resolve: (r: unknown) => void }) => ReactNode };
const kit = vi.hoisted(() => ({ context: vi.fn(), event: null as { value: unknown } | null, resolve: vi.fn() }));
vi.mock("@copilotkit/react-core/v2", () => ({
  useAgentContext: (c: unknown) => kit.context(c),
  useInterrupt: (cfg: Interrupt) =>
    kit.event && cfg.enabled(kit.event) ? cfg.render({ event: kit.event, resolve: kit.resolve }) : null,
}));
const listeners = vi.hoisted(() => ({ current: {} as Record<string, () => void> }));
const chat = vi.hoisted(() => ({
  state: {} as { turns: Turn[]; isRunning: boolean; isReady: boolean; isLoadingHistory: boolean },
  send: vi.fn(),
  args: [] as unknown[],
}));
vi.mock("@/lib/useAgentChat", () => ({
  useAgentChat: (...args: unknown[]) => {
    chat.args = args;
    const agent = { subscribe: (l: Record<string, () => void>) => ((listeners.current = l), { unsubscribe: vi.fn() }) };
    return { agent, send: chat.send, ...chat.state };
  },
}));
const fetchMessages = vi.fn();
vi.mock("@/features/ask/views/proposals/api", async (original) => ({
  ...(await original<typeof import("@/features/ask/views/proposals/api")>()),
  fetchProposalMessages: (id: number) => fetchMessages(id),
}));

import { TellSangam } from "@/features/ask/views/proposals/TellSangam";

beforeAll(() => {
  // jsdom has no scrolling.
  Element.prototype.scrollTo = vi.fn();
});
beforeEach(() => {
  chat.state = { turns: [], isRunning: false, isReady: true, isLoadingHistory: false };
  kit.event = null;
});
afterEach(() => vi.clearAllMocks());

const props = () => ({ proposal: proposal(), screen: { step: "Write the proposal", part: "A1" }, open: true, onTurnEnd: vi.fn(), onSend: vi.fn() });
const turn = (over: Partial<Turn> = {}): Turn => ({ id: "t1", question: "What is missing?", steps: [], answer: "", streaming: false, ...over });

describe("TellSangam", () => {
  it("opens the person's own thread and shares the screen with the agent", async () => {
    const p = props();
    render(<TellSangam {...p} />);
    expect(chat.args.slice(0, 3)).toEqual(["proposal-3-u1", "sangam_proposal", "proposal-chat"]);
    await (chat.args[3] as () => Promise<unknown>)();
    expect(fetchMessages).toHaveBeenCalledWith(3);
    expect(kit.context).toHaveBeenCalledWith({ description: "What the person is looking at", value: p.screen });
    expect(screen.getByText("Ask anything about this step.")).toBeInTheDocument();
    expect(p.onSend).toHaveBeenLastCalledWith(expect.any(Function));
    (p.onSend.mock.lastCall![0] as (t: string) => void)("Write Need.");
    expect(chat.send).toHaveBeenCalledWith("Write Need.");
  });

  it("asks a typed question, by button or by ⌘↵", async () => {
    render(<TellSangam {...props()} />);
    const box = screen.getByRole("textbox", { name: "Ask Sangam Pitch" });
    expect(screen.getByRole("button", { name: "Ask" })).toBeDisabled();
    await userEvent.type(box, "Why this?");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    expect(chat.send).toHaveBeenCalledWith("Why this?");
    expect(box).toHaveValue("");
    await userEvent.type(box, "And that?{Control>}{Enter}{/Control}");
    expect(chat.send).toHaveBeenCalledWith("And that?");
  });

  it("shows past turns without fact marks", () => {
    chat.state.turns = [turn({ answer: "Reach is **500** ⟦k1⟧." })];
    render(<TellSangam {...props()} />);
    expect(screen.getByText("What is missing?")).toBeInTheDocument();
    expect(screen.getByText("500")).toBeInTheDocument();
    expect(screen.queryByText(/⟦k1⟧/)).toBeNull();
  });

  it("is busy while loading, connecting or working", () => {
    chat.state.isLoadingHistory = true;
    const p = props();
    const { rerender } = render(<TellSangam {...p} />);
    expect(screen.getByText("Loading your chat…")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Connecting…" })).toBeDisabled();
    expect(p.onSend).toHaveBeenLastCalledWith(null);
    chat.state = { ...chat.state, isLoadingHistory: false, isRunning: true };
    rerender(<TellSangam {...p} />);
    expect(screen.getByRole("button", { name: "Working…" })).toBeDisabled();
  });

  it("reloads the proposal when a turn ends, and shows a failed run", () => {
    chat.state.isRunning = true;
    const p = props();
    const { rerender } = render(<TellSangam {...p} />);
    chat.state.isRunning = false;
    rerender(<TellSangam {...p} />);
    expect(p.onTurnEnd).toHaveBeenCalledOnce();
    act(() => listeners.current.onRunFailed());
    expect(screen.getByRole("alert")).toHaveTextContent("Sangam Pitch could not answer.");
    act(() => listeners.current.onRunStartedEvent());
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("answers an open question from the chat box", async () => {
    kit.event = {
      value: JSON.stringify({
        type: "proposal_question", id: "q1", ask: "a1", part: "Problem", subject: "dropout", found: "Nothing on dropout",
        missing: "What is the dropout rate?", why: "Funders ask", suggestion: "Annual report", options: ["12%", "Not known"],
      }),
    };
    const p = props();
    render(<TellSangam {...p} />);
    expect(screen.getByText("What is the dropout rate?")).toBeInTheDocument();
    expect(p.onSend).toHaveBeenLastCalledWith(null);
    const box = screen.getByPlaceholderText("Your answer, or a question about it");
    await userEvent.type(box, "About 9%");
    await userEvent.click(screen.getByRole("button", { name: "Reply" }));
    expect(kit.resolve).toHaveBeenCalledWith({ kind: "text", text: "About 9%" });
    expect(chat.send).not.toHaveBeenCalled();
    expect(screen.getByText("Sent.")).toBeInTheDocument();
  });
});

describe("QuestionCard", () => {
  it("sends a picked option, or Later", async () => {
    kit.event = {
      value: { type: "proposal_question", id: "q", ask: "a", part: "Place", subject: "", found: "Assam only", missing: "Which districts?", why: "", suggestion: "", options: ["Dhubri"] },
    };
    render(<TellSangam {...props()} />);
    expect(screen.queryByText(/Why it matters/)).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Dhubri" }));
    expect(kit.resolve).toHaveBeenCalledWith({ kind: "pick", choice: "Dhubri" });
    expect(screen.getByRole("button", { name: "Later" })).toBeDisabled();
  });

  it("offers a suggested rewrite", async () => {
    kit.event = { value: { type: "proposal_suggestion", ask: "s", part: "Problem", now: "Old line", better: "Better line", why: "Clearer" } };
    render(<TellSangam {...props()} />);
    expect(screen.getByRole("region", { name: "Sangam Pitch suggests" })).toHaveTextContent("Better line");
    await userEvent.click(screen.getByRole("button", { name: "Keep mine" }));
    expect(kit.resolve).toHaveBeenCalledWith({ kind: "pick", choice: "keep" });
  });

  it("ignores interrupts that are not its own", () => {
    kit.event = { value: "not json" };
    const { unmount } = render(<TellSangam {...props()} />);
    expect(screen.queryByRole("region", { name: /Sangam Pitch (asks|suggests)/ })).toBeNull();
    unmount();
    kit.event = { value: { type: "choose_sources" } };
    render(<TellSangam {...props()} />);
    expect(screen.queryByRole("region", { name: /Sangam Pitch (asks|suggests)/ })).toBeNull();
  });
});
