import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { MatchList, MatchRow, MeOut } from "@/lib/api";
import { navigation } from "@/tests/setup";

const call = vi.fn();
const getMe = vi.fn();
vi.mock("@/features/ask/lib/rest", () => ({ call: (...a: unknown[]) => call(...a), getMe: () => getMe() }));
const proposals = vi.hoisted(() => ({ rows: [] as unknown[], start: vi.fn() }));
vi.mock("@/features/ask/views/proposals/api", () => ({
  useProposals: () => proposals.rows,
  startProposal: (...a: unknown[]) => proposals.start(...a),
}));
const setUrlParams = vi.fn();
vi.mock("@/lib/url", async (original) => ({
  ...(await original<typeof import("@/lib/url")>()),
  setUrlParams: (...a: unknown[]) => setUrlParams(...a),
}));

import { FunderMatchView } from "@/features/ask/views/FunderMatchView";

const ORGS = [
  { id: 1, slug: "kabil", name: "KABIL" },
  { id: 2, slug: "seva", name: "Seva" },
];
const staff: MeOut = { id: "u", email: null, is_staff: true, is_anonymous: false, memberships: [] };

const row = (id: number, name: string, score: number | null, tier: MatchRow["tier"], type = "corporate_csr"): MatchRow => ({
  id,
  funder: { id: id * 10, slug: name.toLowerCase(), name, funder_type: type },
  score,
  prev_score: id === 1 ? 70 : null,
  tier,
  card: { reasons: [{ kind: "fit", criterion: "theme", text: `${name} funds education` }, { kind: "gap", criterion: "geo", text: `${name} skips Assam` }] },
});

const list = (over: Partial<MatchList> = {}): MatchList => ({
  org: { id: 1, slug: "kabil", name: "KABIL" },
  may_run: true,
  run: { run_id: "r", run_at: "2026-10-01T00:00:00Z", rubric_version: "match-v2", funders_checked: 4, earlier_runs: 2 },
  counts: { strong: 1, medium: 1, weak: 1, not_scored: 1 },
  matches: [
    row(1, "Axis", 82, "strong"),
    row(2, "Tata", 60, "medium", "private_foundation"),
    row(3, "Weakly", 30, "weak"),
    row(4, "Nothing", null, "not_scored"),
  ],
  ...over,
});

const nav = { open: vi.fn(), list: vi.fn() };
const route = (matches: MatchList | Error) =>
  call.mockImplementation(async (path: string, method?: string) => {
    if (path.startsWith("/api/funder-matches/runs")) return { run_id: "n", run_at: "x", funders_checked: 9, tiers: { strong: 2, medium: 3 } };
    if (path.endsWith("/detail")) throw new Error("no detail");
    if (path.startsWith("/api/funder-matches") && !method) {
      if (matches instanceof Error) throw matches;
      return matches;
    }
    throw new Error(`unexpected ${path}`);
  });

beforeEach(() => {
  getMe.mockResolvedValue(staff);
  proposals.rows = [];
});
afterEach(() => vi.clearAllMocks());

describe("FunderMatchView", () => {
  it("asks for the matches straight away when the page already knows who is signed in", async () => {
    route(list());
    render(<FunderMatchView orgs={ORGS} nav={nav} me={staff} />);
    expect(call).toHaveBeenCalledWith("/api/funder-matches?org=kabil");
    expect(await screen.findByRole("article", { name: "Axis" })).toBeInTheDocument();
    expect(getMe).not.toHaveBeenCalled();
  });

  it("ranks the strong and medium funders and folds the rest", async () => {
    route(list());
    render(<FunderMatchView orgs={ORGS} nav={nav} />);
    expect(await screen.findByRole("article", { name: "Axis" })).toBeInTheDocument();
    expect(screen.getByRole("article", { name: "Tata" })).toBeInTheDocument();
    expect(screen.queryByRole("article", { name: "Weakly" })).toBeNull();
    expect(within(screen.getByRole("article", { name: "Axis" })).getByText("▲ 12 since the last run")).toBeInTheDocument();
    expect(screen.getByText(/Latest run .* 4 funders checked · 2 earlier runs/)).toBeInTheDocument();
    expect(screen.getByText("2 of 2 scored funders · ranked by fit score, highest first")).toBeInTheDocument();
    expect(screen.getByText(/Weak or no fit · 2 scored below 55/)).toBeInTheDocument();
    expect(screen.getByText("Not scored")).toBeInTheDocument();
    expect(call).toHaveBeenCalledWith("/api/funder-matches?org=kabil");
    expect(screen.getByRole("combobox", { name: /Organisation · all/ })).toHaveValue("kabil");
  });

  it("narrows by bucket, funder type and search", async () => {
    route(list());
    render(<FunderMatchView orgs={ORGS} nav={nav} />);
    await screen.findByRole("article", { name: "Axis" });
    await userEvent.click(screen.getByRole("button", { name: /Strong/ }));
    expect(screen.queryByRole("article", { name: "Tata" })).toBeNull();
    expect(screen.queryByText(/Weak or no fit/)).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: /All fits/ }));
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Funder type" }), "Private or family foundation");
    expect(screen.queryByRole("article", { name: "Axis" })).toBeNull();
    expect(screen.getByRole("article", { name: "Tata" })).toBeInTheDocument();
    await userEvent.type(screen.getByRole("searchbox"), "zzz");
    expect(screen.getByText("No funders match these filters for KABIL.")).toBeInTheDocument();
  });

  it("filters by whether a proposal was started", async () => {
    proposals.rows = [{ id: 7, org: { slug: "kabil" }, funder: { id: 10 } }];
    route(list());
    render(<FunderMatchView orgs={ORGS} nav={nav} />);
    await screen.findByRole("article", { name: "Axis" });
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Proposal" }), "none");
    expect(screen.queryByRole("article", { name: "Axis" })).toBeNull();
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Proposal" }), "has");
    expect(screen.getByRole("article", { name: "Axis" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Continue proposal →" }));
    expect(nav.open).toHaveBeenCalledWith(7);
  });

  it("reruns the match for the active organisation and reloads", async () => {
    route(list());
    render(<FunderMatchView orgs={ORGS} nav={nav} />);
    await userEvent.click(await screen.findByRole("button", { name: "Rerun match" }));
    expect(call).toHaveBeenCalledWith("/api/funder-matches/runs?org=kabil", "POST");
    expect(await screen.findByRole("status")).toHaveTextContent("Saved · 9 funders checked · 2 strong, 3 medium");
    await waitFor(() => expect(call.mock.calls.filter(([p]) => p === "/api/funder-matches?org=kabil")).toHaveLength(2));
  });

  it("shows a failed rerun", async () => {
    route(list());
    render(<FunderMatchView orgs={ORGS} nav={nav} />);
    await screen.findByRole("article", { name: "Axis" });
    call.mockRejectedValueOnce(new Error("Only stewards may run"));
    await userEvent.click(screen.getByRole("button", { name: "Rerun match" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Only stewards may run");
  });

  it("picks another organisation through the address", async () => {
    route(list());
    render(<FunderMatchView orgs={ORGS} nav={nav} />);
    await screen.findByRole("article", { name: "Axis" });
    await userEvent.selectOptions(screen.getByRole("combobox", { name: /Organisation/ }), "seva");
    expect(setUrlParams).toHaveBeenCalledWith({ org: "seva" }, "replace");
  });

  it("uses the organisation in the address when it is one of yours", async () => {
    navigation.search = new URLSearchParams("org=seva");
    route(list({ org: { id: 2, slug: "seva", name: "Seva" } }));
    render(<FunderMatchView orgs={ORGS} nav={nav} />);
    await screen.findByRole("article", { name: "Axis" });
    expect(call).toHaveBeenCalledWith("/api/funder-matches?org=seva");
  });

  it("says when no match is saved yet, for a runner and a reader", async () => {
    route(list({ run: null, matches: [] }));
    const { unmount } = render(<FunderMatchView orgs={ORGS} nav={nav} />);
    expect(await screen.findByText("No match saved for KABIL yet")).toBeInTheDocument();
    expect(screen.getByText("Not run yet")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run the first match" })).toBeInTheDocument();
    unmount();
    route(list({ run: null, matches: [], may_run: false }));
    render(<FunderMatchView orgs={ORGS} nav={nav} />);
    expect(await screen.findByText(/Its stewards, admins or Sangam staff/)).toBeInTheDocument();
  });

  it("shows a member their one organisation, fixed", async () => {
    getMe.mockResolvedValue({ ...staff, is_staff: false, memberships: [{ org_id: 1, org_slug: "kabil", org_name: "KABIL", role: "member" }] });
    route(list({ may_run: false }));
    render(<FunderMatchView orgs={ORGS} nav={nav} />);
    await screen.findByRole("article", { name: "Axis" });
    expect(screen.getByText("Your organisation")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Rerun/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Start a proposal" })).toBeNull();
  });

  it("labels the picker for a steward of several organisations", async () => {
    const memberships = ORGS.map((o) => ({ org_id: o.id, org_slug: o.slug, org_name: o.name, role: "steward" }));
    getMe.mockResolvedValue({ ...staff, is_staff: false, memberships });
    route(list());
    render(<FunderMatchView orgs={ORGS} nav={nav} />);
    expect(await screen.findByRole("combobox", { name: /Organisation · 2 you steward/ })).toBeInTheDocument();
  });

  it("tells someone with no organisation what to do", async () => {
    getMe.mockResolvedValue({ ...staff, is_staff: false, memberships: [] });
    render(<FunderMatchView orgs={ORGS} nav={nav} />);
    expect(await screen.findByText("Funder Match works for an organisation")).toBeInTheDocument();
    expect(call).not.toHaveBeenCalled();
  });

  it("shows loading, then a failed load", async () => {
    route(new Error("Matches unavailable"));
    render(<FunderMatchView orgs={ORGS} nav={nav} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Matches unavailable");
    expect(screen.queryByText("Loading…")).toBeNull();
  });

  it("shows a failed sign-in lookup", async () => {
    getMe.mockRejectedValue(new Error("Sign in again"));
    render(<FunderMatchView orgs={ORGS} nav={nav} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Sign in again");
  });
});
