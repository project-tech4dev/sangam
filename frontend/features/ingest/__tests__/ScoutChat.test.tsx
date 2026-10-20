import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { TraceStep, Turn } from "@/lib/useAgentChat";
import type { ImportAccess } from "../lib/access";
import { EMPTY_SOURCES } from "../lib/sourcePick";
import { coverage, review, stubFetch } from "../components/__tests__/fakes";

const chat = vi.hoisted(() => ({
  turns: [] as Turn[],
  isRunning: false,
  isReady: true,
  isLoadingHistory: false,
  laneOwners: {} as Record<string, string>,
  send: vi.fn(async (value: string) => void value),
  stop: vi.fn(),
  waitingOn: null as string | null,
  context: vi.fn(),
  askLive: vi.fn(),
  hookArgs: [] as unknown[],
}));

vi.mock("@/lib/useAgentChat", () => ({
  useAgentChat: (...args: unknown[]) => {
    chat.hookArgs = args;
    return { agent: {}, ...chat };
  },
}));
vi.mock("@copilotkit/react-core/v2", () => ({
  useAgentContext: (ctx: unknown) => chat.context(ctx),
  useInterrupt: () => null,
}));
vi.mock("../lib/useRunPause", () => ({ useRunPause: () => chat.waitingOn }));
vi.mock("../lib/threads", () => ({
  askLive: (...a: unknown[]) => chat.askLive(...a),
  fetchImportMessages: vi.fn(async () => []),
}));
vi.mock("@/lib/api/auth-headers", () => ({ authHeaders: async () => ({}) }));

import { ScoutChat } from "../ScoutChat";

const STEWARD: ImportAccess = { staff: false, stewardOf: ["A"], orgs: [{ slug: "a", name: "A" }] };
const STAFF: ImportAccess = { staff: true, stewardOf: [], orgs: [] };

let n = 0;
const step = (tool: string, args: unknown, result: string | null, extra: Partial<TraceStep> = {}): TraceStep => ({
  id: `s${++n}`, tool, args, result, running: result === null, ...extra,
});
const turn = (over: Partial<Turn> = {}): Turn => ({ id: `t${++n}`, question: "Funding profile for KABIL", steps: [], answer: "", streaming: false, ...over });
const researching = () => step("task", { description: "KABIL — funding", subagent_type: "entity-researcher" }, null);

function renderChat(props: Partial<Parameters<typeof ScoutChat>[0]> = {}) {
  const onStartOver = vi.fn();
  const onFirstSend = vi.fn();
  const utils = render(
    <ScoutChat threadId="import-1" onStartOver={onStartOver} onFirstSend={onFirstSend} access={STEWARD} staff={null} {...props} />,
  );
  return { ...utils, onStartOver, onFirstSend };
}

beforeEach(() => {
  Object.assign(chat, { turns: [], isRunning: false, isReady: true, isLoadingHistory: false, laneOwners: {}, waitingOn: null });
  chat.send.mockClear();
  chat.stop.mockClear();
  chat.context.mockClear();
  chat.askLive.mockReset();
  vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: false })));
  stubFetch({ "/workbooks": [] });
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("ScoutChat, before the first message", () => {
  it("offers a steward the two research tasks and a staff member all four", () => {
    const { unmount } = renderChat();
    expect(screen.getAllByRole("radio").map((r) => r.textContent)).toEqual([
      expect.stringContaining("Research a funder"),
      expect.stringContaining("Check an NGO"),
    ]);
    unmount();
    renderChat({ access: STAFF });
    expect(screen.getAllByRole("radio")).toHaveLength(4);
  });

  it("needs a source before a research task can be sent, then sends it with the ticked sources", async () => {
    const { onFirstSend } = renderChat();
    await userEvent.click(screen.getByRole("radio", { name: /Research a funder/ }));
    const box = screen.getByRole("textbox", { name: "Message Scout" });
    expect(box).toHaveValue("Funding profile for ");
    expect(screen.getByText("Choose where Scout reads from first.")).toBeInTheDocument();
    const send = screen.getByRole("button", { name: "Send to Scout" });
    expect(send).toBeDisabled();

    // The inline picker and the rail's both set the same choice.
    await userEvent.click(screen.getAllByRole("checkbox", { name: /Public websites/ })[0]!);
    expect(chat.context).toHaveBeenLastCalledWith({
      description: "Sources the person ticked for this Import run",
      value: { ...EMPTY_SOURCES, web: true },
    });
    await userEvent.type(box, "KABIL");
    expect(send).toBeEnabled();
    await userEvent.click(send);
    expect(onFirstSend).toHaveBeenCalledWith("Funding profile for KABIL");
    expect(chat.send).toHaveBeenCalledWith("Funding profile for KABIL");
    expect(box).toHaveValue("");
  });

  it("sends a fixed pull with ⌘↵ and no sources step", async () => {
    renderChat({ access: STAFF });
    await userEvent.click(screen.getByRole("radio", { name: /Get the latest news/ }));
    expect(screen.queryByText("Choose where Scout reads from first.")).not.toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole("textbox", { name: "Message Scout" }), { key: "Enter", metaKey: true });
    await waitFor(() => expect(chat.send).toHaveBeenCalledWith("Get the latest news for everyone in Sangam"));
  });

  it("waits while Scout connects", () => {
    chat.isReady = false;
    renderChat();
    expect(screen.getByText("Connecting to Scout…")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Message Scout" })).toBeDisabled();
  });

  it("shows what goes under the empty composer", () => {
    renderChat({ below: <p>Researched recently</p> });
    expect(screen.getByText("Researched recently")).toBeInTheDocument();
  });
});

describe("ScoutChat, during and after a run", () => {
  it("loads a resumed thread's history", () => {
    chat.isLoadingHistory = true;
    chat.turns = [turn()];
    renderChat({ resume: true });
    expect(screen.getByText("Opening this chat…")).toBeInTheDocument();
    expect(chat.hookArgs.slice(0, 3)).toEqual(["import-1", "sangam_ingest", "sangam-import"]);
    expect(typeof chat.hookArgs[3]).toBe("function");
  });

  it("shows a running research turn with its progress panel, and stops it", async () => {
    chat.isRunning = true;
    chat.turns = [turn({ streaming: true, steps: [researching()], answer: "Starting on **KABIL**" })];
    renderChat();
    expect(screen.getByText("Funding profile for KABIL")).toBeInTheDocument();
    expect(screen.getAllByText("KABIL", { selector: "strong" }).length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("0 of 1 organisation ready")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Researching 1 organisation/ })).toHaveTextContent("shown above");
    // Working opens the panel on its own.
    expect(screen.getByRole("button", { name: "Close ✕" })).toBeInTheDocument();
    expect(screen.getByText("Scout is researching. Ask about progress, ⌘↵ to send.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Stop" }));
    expect(chat.stop).toHaveBeenCalledOnce();
  });

  it("answers a question asked mid-run from the run's state, without sending it", async () => {
    chat.isRunning = true;
    chat.turns = [turn({ streaming: true, steps: [researching()] })];
    chat.askLive.mockResolvedValue({ answer: "Reading kabil.org now.", kind: "status" });
    renderChat();
    await userEvent.type(screen.getByRole("textbox", { name: "Message Scout" }), "How far along?");
    await userEvent.click(screen.getByRole("button", { name: "Ask Scout" }));
    expect(await screen.findByText("Reading kabil.org now.")).toBeInTheDocument();
    expect(chat.askLive).toHaveBeenCalledWith("import-1", "How far along?", null, [{ owner: null, tool: "task", running: true }]);
    expect(chat.send).not.toHaveBeenCalled();
  });

  it("holds an instruction given mid-run and sends it once the run ends", async () => {
    chat.isRunning = true;
    chat.turns = [turn({ streaming: true, steps: [researching()] })];
    chat.askLive.mockResolvedValueOnce({ answer: "I'll do that next.", kind: "instruction" }).mockRejectedValueOnce(new Error("Scout could not answer right now (502)."));
    const { rerender } = renderChat();
    const box = screen.getByRole("textbox", { name: "Message Scout" });
    await userEvent.type(box, "Also check Tata");
    await userEvent.click(screen.getByRole("button", { name: "Ask Scout" }));
    expect(await screen.findByText("Scout will pick up your request when the current researchers finish.")).toBeInTheDocument();
    await userEvent.type(box, "Status?");
    await userEvent.click(screen.getByRole("button", { name: "Ask Scout" }));
    expect(await screen.findByText("Scout could not answer right now (502).")).toBeInTheDocument();

    chat.isRunning = false;
    chat.turns = [turn({ id: chat.turns[0]!.id, steps: [step("task", { description: "KABIL — x" }, "done")] })];
    rerender(<ScoutChat threadId="import-1" onStartOver={vi.fn()} access={STEWARD} staff={null} />);
    await waitFor(() => expect(chat.send).toHaveBeenCalledWith("Also check Tata"));
  });

  it("says when the run waits on a card that never opened", () => {
    chat.turns = [turn()];
    chat.waitingOn = "promote_research";
    renderChat();
    expect(screen.getByText(/waiting for you to review what to save, but the card did not open/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send to Scout" })).toBeDisabled();
  });

  it("reaches Review after research, with the Done cards in the panel", async () => {
    stubFetch({ "/research/kabil/coverage": coverage(), "/research/kabil/review": review(), "/queue": [] });
    chat.turns = [
      turn({
        steps: [
          step("task", { description: "KABIL — x", subagent_type: "entity-researcher" }, JSON.stringify({ status: "ready", slug: "kabil" })),
          step("search_public_sources", { query: "kabil" }, "REFUSED: not an allowed site"),
          step("search_public_sources", { query: "kabil" }, "REFUSED: not an allowed site"),
        ],
        answer: "Here is what I found.",
      }),
    ];
    renderChat();
    expect(screen.getByText("Here is what I found.")).toBeInTheDocument();
    expect(screen.getAllByText(/Researched 1 organisation/)).toHaveLength(2);
    expect(screen.getByText("×2")).toBeInTheDocument();
    const open = await screen.findByRole("button", { name: "Review 1 →" }, { timeout: 2000 });
    await userEvent.click(open);
    expect(screen.getByRole("region", { name: "Review" })).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Close ✕" }));
    // The thread's marker opens it again.
    await userEvent.click(screen.getByRole("button", { name: /Researched 1 organisation/ }));
    expect(screen.getByRole("button", { name: "Close ✕" })).toBeInTheDocument();
  });

  it("calls a file-reading turn with no organisations done", () => {
    chat.turns = [turn({ steps: [step("task", { subagent_type: "vault-reader" }, "ok")] })];
    renderChat();
    expect(screen.getByRole("button", { name: /Read your files/ })).toBeInTheDocument();
    expect(screen.getByText("Reading finished")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show" })).toBeInTheDocument();
  });

  it("pins an earlier run to the panel from its marker", async () => {
    const first = turn({ question: "First", steps: [step("task", { subagent_type: "workbook-reader" }, "ok")] });
    const second = turn({ question: "Second", steps: [step("task", { subagent_type: "vault-reader" }, null)], streaming: true });
    chat.turns = [first, second];
    renderChat();
    expect(screen.getByRole("button", { name: /Reading your files/ })).toHaveTextContent("shown above");
    await userEvent.click(screen.getByRole("button", { name: /^Read your files/ }));
    expect(screen.getByRole("button", { name: /^Read your files/ })).toHaveTextContent("shown above");
    expect(screen.getByRole("button", { name: /Reading your files/ })).toHaveTextContent("· show above");
  });

  it("starts over, asking first while a run is going", async () => {
    chat.turns = [turn()];
    const { onStartOver, rerender } = renderChat();
    await userEvent.click(screen.getByRole("button", { name: "New chat" }));
    expect(onStartOver).toHaveBeenCalledOnce();

    chat.isRunning = true;
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    rerender(<ScoutChat threadId="import-1" onStartOver={onStartOver} access={STEWARD} staff={null} />);
    await userEvent.click(screen.getByRole("button", { name: "New chat" }));
    expect(onStartOver).toHaveBeenCalledOnce();
    await userEvent.click(screen.getByRole("button", { name: "New chat" }));
    expect(confirm).toHaveBeenCalledTimes(2);
    expect(chat.stop).toHaveBeenCalledOnce();
    expect(onStartOver).toHaveBeenCalledTimes(2);
  });

  it("sends a follow-up after a finished turn", async () => {
    chat.turns = [turn({ answer: "Done." })];
    renderChat();
    const box = screen.getByRole("textbox", { name: "Message Scout" });
    await userEvent.type(box, "And Tata?");
    await act(async () => fireEvent.keyDown(box, { key: "Enter", ctrlKey: true }));
    expect(chat.send).toHaveBeenCalledWith("And Tata?");
    // A plain Enter is a new line, not a send.
    fireEvent.keyDown(box, { key: "Enter" });
    expect(chat.send).toHaveBeenCalledOnce();
  });
});
