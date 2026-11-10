import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { status, stubFetch } from "./fakes";

type Config = {
  enabled: (e: { value: unknown }) => boolean;
  render: (p: { event: { value: unknown }; resolve: (v: unknown) => void }) => ReactElement;
};
const pause = vi.hoisted(() => ({ event: null as { value: unknown } | null, resolve: vi.fn() }));

vi.mock("@copilotkit/react-core/v2", () => ({
  useInterrupt: (cfg: Config) => (pause.event && cfg.enabled(pause.event) ? cfg.render({ event: pause.event, resolve: pause.resolve }) : null),
}));
vi.mock("@/lib/api/auth-headers", () => ({ authHeaders: async () => ({}) }));

import { ImportApproval, pausedImport } from "../ImportApproval";

const runNow = (args: Record<string, unknown>) => ({ value: { action_requests: [{ name: "run_import_now", args }] } });
const plan = {
  everyone: false,
  subjects: 2,
  records: 2,
  searches: 6,
  checks: 0,
  cost_usd: 0.4,
  matched: ["KABIL"],
  feeds: ["FCRA"],
  unmatched: ["Nobody Ltd"],
};

beforeEach(() => {
  pause.event = null;
  pause.resolve.mockReset();
});
afterEach(() => vi.unstubAllGlobals());

describe("pausedImport", () => {
  it("reads the plan's strings and blanks anything else", () => {
    expect(pausedImport(runNow({ goal: "g", funders: 3 }).value)).toEqual({ goal: "g", funders: "", years: "", sources: "", feeds: "" });
    expect(pausedImport({ action_requests: [{ name: "choose_sources" }] })).toBeNull();
  });
});

describe("ImportApproval", () => {
  it("asks to write a catalog import, and approves", async () => {
    pause.event = runNow({ goal: "Refresh CSR", funders: "", years: "2024", sources: "" });
    const onPaused = vi.fn();
    render(<ImportApproval agentId="a" onPaused={onPaused} />);
    expect(onPaused).toHaveBeenCalledWith(true);
    expect(screen.getByText("Refresh CSR")).toBeInTheDocument();
    expect(
      screen.getByText("Funders: whatever was published most recently · Years: 2024 · Sources: every registered source"),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Approve and write" }));
    expect(pause.resolve).toHaveBeenCalledWith({ decisions: [{ type: "approve" }] });
    expect(screen.getByRole("button", { name: "Don't write" })).toBeDisabled();
  });

  it("says when no goal was given, and rejects", async () => {
    pause.event = runNow({});
    render(<ImportApproval agentId="a" onPaused={vi.fn()} />);
    expect(screen.getByText("No goal given.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Don't write" }));
    expect(pause.resolve).toHaveBeenCalledWith({ decisions: [{ type: "reject" }] });
  });

  it("asks about an open-calls pull with who and what it costs", async () => {
    pause.event = runNow({ sources: "funder_calls", funders: "KABIL, Tata Trusts" });
    const { unmount } = render(<ImportApproval agentId="a" onPaused={vi.fn()} />);
    expect(screen.getByText("2 funders: KABIL, Tata Trusts · about 1 search and 2 small model calls per funder")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Don't check" }));
    expect(pause.resolve).toHaveBeenCalledWith({ decisions: [{ type: "reject" }] });
    unmount();
    pause.event = runNow({ sources: "funder_calls", funders: "KABIL" });
    const r = render(<ImportApproval agentId="a" onPaused={vi.fn()} />);
    expect(screen.getByText(/^1 funder: KABIL/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Check the calls" }));
    expect(pause.resolve).toHaveBeenLastCalledWith({ decisions: [{ type: "approve" }] });
    r.unmount();
    pause.event = runNow({ sources: "funder_calls" });
    render(<ImportApproval agentId="a" onPaused={vi.fn()} />);
    expect(screen.getByText(/^Every funder in Sangam/)).toBeInTheDocument();
  });

  it("states the news plan the pull will run", async () => {
    const fetchMock = stubFetch({ "/news-runs/plan": plan });
    pause.event = runNow({ sources: "tavily_news", funders: "KABIL, Nobody Ltd", feeds: "FCRA" });
    render(<ImportApproval agentId="a" onPaused={vi.fn()} />);
    expect(screen.getByText("Working out what this pull would search…")).toBeInTheDocument();
    expect(
      await screen.findByText(
        "News for KABIL (their own news), plus topic news: FCRA · about 6 searches · about $0.40. No Registry record for: Nobody Ltd",
      ),
    ).toBeInTheDocument();
    expect(String(fetchMock.mock.calls[0]![0])).toContain("names=KABIL%2C%20Nobody%20Ltd&feeds=FCRA");
    await userEvent.click(screen.getByRole("button", { name: "Pull the news" }));
    expect(pause.resolve).toHaveBeenCalledWith({ decisions: [{ type: "approve" }] });
  });

  it("words a news pull for everyone, topics alone, and a failed plan", async () => {
    stubFetch({ "/news-runs/plan": { ...plan, everyone: true, records: 40, feeds: [], unmatched: [], checks: 5 } });
    pause.event = runNow({ sources: "tavily_news" });
    const a = render(<ImportApproval agentId="a" onPaused={vi.fn()} />);
    expect(
      await screen.findByText("News for everyone in Sangam (40 organisations and funders) · about 6 searches · up to 5 checks by reading · about $0.40"),
    ).toBeInTheDocument();
    a.unmount();

    stubFetch({ "/news-runs/plan": { ...plan, matched: [], unmatched: [] } });
    const b = render(<ImportApproval agentId="a" onPaused={vi.fn()} />);
    expect(await screen.findByText("Topic news: FCRA · about 6 searches · about $0.40")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Don't pull" }));
    expect(pause.resolve).toHaveBeenCalledWith({ decisions: [{ type: "reject" }] });
    b.unmount();

    stubFetch({ "/news-runs/plan": status(500) });
    render(<ImportApproval agentId="a" onPaused={vi.fn()} />);
    expect(await screen.findByText("Could not work out the plan; approving still runs the pull.")).toBeInTheDocument();
  });

  it("stays empty for another pause", () => {
    pause.event = { value: { action_requests: [{ name: "choose_sources" }] } };
    const { container } = render(<ImportApproval agentId="a" onPaused={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });
});
