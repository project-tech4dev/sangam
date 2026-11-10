import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { MatchDetail, MatchRow } from "@/lib/api";

const call = vi.fn();
vi.mock("@/features/ask/lib/rest", () => ({ call: (...a: unknown[]) => call(...a) }));
const proposals = vi.hoisted(() => ({ rows: [] as unknown[], start: vi.fn() }));
vi.mock("@/features/ask/views/proposals/api", () => ({
  useProposals: () => proposals.rows,
  startProposal: (...a: unknown[]) => proposals.start(...a),
}));

import { MatchCard } from "@/features/ask/views/funder-match/MatchCard";

const match: MatchRow = {
  id: 5,
  funder: { id: 50, slug: "axis", name: "Axis", funder_type: null },
  score: 60,
  prev_score: 72,
  tier: "medium",
  card: { reasons: [{ kind: "gap", criterion: "geo", text: "Works outside Assam" }] },
};
const detail: MatchDetail = {
  id: 5,
  run_at: "2026-10-01T00:00:00Z",
  rubric_version: "match-v2",
  detail: {
    summary: "A medium fit on theme.",
    criteria: [
      { code: "theme", label: "Theme", max: 25, points: 15, status: "partial", note: "Education clause", cites: ["[org:1]"] },
      { code: "geo", label: "Geography", max: 15, points: null, status: "unknown", note: "No places", cites: [] },
    ],
    score: null,
    not_judged: ["Capacity is not recorded."],
    improve: ["Add districts served."],
  },
};
const org = { slug: "kabil", name: "KABIL" };
const nav = { open: vi.fn(), list: vi.fn() };

// jsdom fires the toggle event itself once `open` changes.
const openDetails = () => userEvent.click(screen.getByText("Why this score"));

afterEach(() => {
  vi.clearAllMocks();
  proposals.rows = [];
});

describe("MatchCard", () => {
  it("shows the score, a drop since the last run and the reasons", () => {
    render(<MatchCard match={match} rank={3} org={org} nav={nav} mayStart />);
    expect(screen.getByText("#3")).toBeInTheDocument();
    expect(screen.getByText("Medium fit")).toBeInTheDocument();
    expect(screen.getByText("▼ 12 since the last run")).toBeInTheDocument();
    expect(screen.getByText("Other")).toBeInTheDocument();
    expect(screen.getByText("Works outside Assam")).toBeInTheDocument();
  });

  it("loads the criterion-by-criterion detail once, on opening", async () => {
    call.mockResolvedValue(detail);
    render(<MatchCard match={match} rank={1} org={org} nav={nav} mayStart />);
    await openDetails();
    expect(await screen.findByText("A medium fit on theme.")).toBeInTheDocument();
    expect(call).toHaveBeenCalledWith("/api/funder-matches/5/detail");
    expect(screen.getByText("15 / 25")).toBeInTheDocument();
    expect(screen.getByText("unknown")).toBeInTheDocument();
    expect(screen.getByText("Capacity is not recorded.")).toBeInTheDocument();
    expect(screen.getByText("Add districts served.")).toBeInTheDocument();
    await openDetails();
    await openDetails();
    expect(call).toHaveBeenCalledOnce();
  });

  it("shows a failed detail load", async () => {
    call.mockRejectedValue(new Error("Detail gone"));
    render(<MatchCard match={match} rank={1} org={org} nav={nav} mayStart />);
    await openDetails();
    expect(await screen.findByText("Detail gone")).toBeInTheDocument();
  });

  it("starts a named proposal and opens it", async () => {
    proposals.start.mockResolvedValue(42);
    render(<MatchCard match={match} rank={1} org={org} nav={nav} mayStart />);
    await userEvent.click(screen.getByRole("button", { name: "Start a proposal" }));
    const name = screen.getByRole("textbox", { name: "Proposal name" });
    expect(name).toHaveValue("Axis proposal");
    await userEvent.clear(name);
    expect(screen.getByRole("button", { name: "Start" })).toBeDisabled();
    await userEvent.type(name, " Axis 2027 ");
    await userEvent.click(screen.getByRole("button", { name: "Start" }));
    expect(proposals.start).toHaveBeenCalledWith("kabil", 50, "Axis 2027");
    await waitFor(() => expect(nav.open).toHaveBeenCalledWith(42));
  });

  it("keeps the form open with the reason when starting fails, and cancels", async () => {
    proposals.start.mockRejectedValue(new Error("Not allowed"));
    render(<MatchCard match={match} rank={1} org={org} nav={nav} mayStart />);
    await userEvent.click(screen.getByRole("button", { name: "Start a proposal" }));
    await userEvent.click(screen.getByRole("button", { name: "Start" }));
    expect(await screen.findByText("Not allowed")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByRole("button", { name: "Start a proposal" })).toBeInTheDocument();
  });

  it("lists several started proposals, and a member only views one", async () => {
    proposals.rows = [
      { id: 1, org: { slug: "kabil" }, funder: { id: 50 } },
      { id: 2, org: { slug: "kabil" }, funder: { id: 50 } },
    ];
    const { unmount } = render(<MatchCard match={match} rank={1} org={org} nav={nav} mayStart />);
    await userEvent.click(screen.getByRole("button", { name: "Proposals (2) →" }));
    expect(nav.list).toHaveBeenCalledWith(50);
    expect(screen.getByRole("button", { name: "Start another" })).toBeInTheDocument();
    unmount();
    proposals.rows = [{ id: 1, org: { slug: "kabil" }, funder: { id: 50 } }];
    render(<MatchCard match={match} rank={1} org={org} nav={nav} mayStart={false} />);
    expect(screen.getByRole("button", { name: "View proposal →" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Start/ })).toBeNull();
  });
});
