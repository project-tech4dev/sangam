import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { MeOut } from "@/lib/api";
import type { Feed, FeedCall } from "@/features/ask/views/rfp-watch/api";

const call = vi.fn();
const getMe = vi.fn();
vi.mock("@/features/ask/lib/rest", () => ({ call: (...a: unknown[]) => call(...a), getMe: () => getMe() }));

import { RfpWatchView } from "@/features/ask/views/RfpWatchView";
import { daysLeft } from "@/features/ask/views/rfp-watch/CallCard";

const ORGS = [
  { id: 1, slug: "kabil", name: "KABIL" },
  { id: 2, slug: "seva", name: "Seva" },
];
const staff: MeOut = { id: "u", email: null, is_staff: true, is_anonymous: false, memberships: [] };

// A date `n` days from today, as the API sends it.
const inDays = (n: number) => {
  const d = new Date();
  d.setDate(d.getDate() + n);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

const callRow = (rfp_id: number, title: string, over: Partial<FeedCall> = {}): FeedCall => ({
  rfp_id,
  title,
  funder_id: 1,
  funder_name: "Axis",
  url: "https://axis.example/call",
  source_url: null,
  deadline: inDays(60),
  amount_min: null,
  amount_max: null,
  call_status: "open",
  status: "flagged",
  places: [],
  themes: ["Education"],
  ...over,
});

const feed = (over: Partial<Feed> = {}): Feed => ({
  org_id: 1,
  org_name: "KABIL",
  can_act: true,
  domains: ["Education", "Health"],
  last_pulled: "2026-10-15",
  items: [
    callRow(1, "School libraries", { amount_min: 500000, amount_max: 2000000, places: ["Assam"] }),
    callRow(2, "Clinic grants", { deadline: inDays(5), themes: ["Health"], amount_max: 100000, funder_name: null, url: "javascript:x" }),
    callRow(3, "Old call", { deadline: inDays(-3), status: "saved", amount_min: 100000 }),
    callRow(4, "Today call", { deadline: inDays(0), amount_min: 100, amount_max: 100 }),
  ],
  ...over,
});

const route = (f: Feed | Error) =>
  call.mockImplementation(async (path: string, method?: string) => {
    if (method === "PATCH") return { status: "ok" };
    if (f instanceof Error) throw f;
    return f;
  });

const props = { orgs: ORGS, onAsk: vi.fn(), onFunderMatch: vi.fn() };

beforeEach(() => getMe.mockResolvedValue(staff));
afterEach(() => vi.clearAllMocks());

describe("RfpWatchView", () => {
  it("asks for the feed straight away when the page already knows who is signed in", async () => {
    route(feed());
    render(<RfpWatchView {...props} me={staff} />);
    expect(call).toHaveBeenCalledWith("/api/rfps/feed?org=kabil");
    expect(await screen.findByRole("article", { name: "School libraries" })).toBeInTheDocument();
    expect(getMe).not.toHaveBeenCalled();
  });

  it("lists open calls in the organisation's theme, with their deadlines and amounts", async () => {
    route(feed());
    render(<RfpWatchView {...props} />);
    const libraries = await screen.findByRole("article", { name: "School libraries" });
    expect(call).toHaveBeenCalledWith("/api/rfps/feed?org=kabil");
    expect(screen.getByText(/Calls from funders on Sangam whose theme matches KABIL/)).toBeInTheDocument();
    expect(within(libraries).getByText("₹5 lakh – ₹20 lakh")).toBeInTheDocument();
    expect(within(libraries).getByText("Assam")).toBeInTheDocument();
    expect(within(libraries).getByRole("link", { name: /Read the call/ })).toHaveAttribute("href", "https://axis.example/call");
    const clinic = screen.getByRole("article", { name: "Clinic grants" });
    expect(within(clinic).getByText("5 days left")).toBeInTheDocument();
    expect(within(clinic).getByText("Up to ₹1 lakh")).toBeInTheDocument();
    expect(within(clinic).getByText("Funder not recorded")).toBeInTheDocument();
    expect(within(clinic).queryByRole("link")).toBeNull();
    expect(within(screen.getByRole("article", { name: "Today call" })).getByText("Due today")).toBeInTheDocument();
    expect(screen.queryByRole("article", { name: "Old call" })).toBeNull();
    expect(screen.getByText("3 calls, soonest deadline first")).toBeInTheDocument();
  });

  it("switches buckets, theme and search", async () => {
    route(feed());
    render(<RfpWatchView {...props} />);
    await screen.findByRole("article", { name: "School libraries" });
    await userEvent.click(screen.getByRole("button", { name: /Closing soon/ }));
    expect(screen.queryByRole("article", { name: "School libraries" })).toBeNull();
    expect(screen.getByRole("article", { name: "Clinic grants" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Saved/ }));
    const old = screen.getByRole("article", { name: "Old call" });
    expect(within(old).getAllByText("Closed")).toHaveLength(1);
    expect(within(old).getByText("From ₹1 lakh")).toBeInTheDocument();
    expect(within(old).getByRole("button", { name: "Remove" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /For you/ }));
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Theme" }), "Health");
    expect(screen.getAllByRole("article")).toHaveLength(1);
    await userEvent.type(screen.getByRole("searchbox"), "nothing like it");
    expect(screen.getByText("No calls match this search.")).toBeInTheDocument();
  });

  it("saves a call and dismisses another", async () => {
    route(feed());
    render(<RfpWatchView {...props} />);
    const libraries = await screen.findByRole("article", { name: "School libraries" });
    await userEvent.click(within(libraries).getByRole("button", { name: "Save" }));
    expect(call).toHaveBeenCalledWith("/api/rfps/1/matches/1", "PATCH", { status: "saved" });
    expect(await within(libraries).findByRole("button", { name: "Saved" })).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(within(libraries).getByRole("button", { name: "Saved" }));
    expect(call).toHaveBeenCalledWith("/api/rfps/1/matches/1", "PATCH", { status: "flagged" });
    await userEvent.click(within(screen.getByRole("article", { name: "Clinic grants" })).getByRole("button", { name: "Not for us" }));
    expect(call).toHaveBeenCalledWith("/api/rfps/2/matches/1", "PATCH", { status: "dismissed" });
    expect(screen.queryByRole("article", { name: "Clinic grants" })).toBeNull();
  });

  it("shows a change that was not saved", async () => {
    route(feed());
    render(<RfpWatchView {...props} />);
    const libraries = await screen.findByRole("article", { name: "School libraries" });
    call.mockRejectedValueOnce(new Error("Not a member"));
    await userEvent.click(within(libraries).getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Not a member");
  });

  it("asks Sangam about a call, and offers Funder Match", async () => {
    route(feed());
    render(<RfpWatchView {...props} />);
    const libraries = await screen.findByRole("article", { name: "School libraries" });
    await userEvent.click(within(libraries).getByRole("button", { name: "Ask about this call" }));
    expect(props.onAsk).toHaveBeenCalledWith(expect.stringMatching(/^Help me decide whether KABIL should apply to Axis's call "School libraries", due /));
    await userEvent.click(screen.getByRole("button", { name: "Try Funder Match" }));
    expect(props.onFunderMatch).toHaveBeenCalled();
  });

  it("lets a reader see but not change calls", async () => {
    route(feed({ can_act: false }));
    render(<RfpWatchView {...props} />);
    await screen.findByRole("article", { name: "School libraries" });
    expect(screen.getAllByText("Only members and admins of KABIL can save or hide calls.").length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
  });

  it("explains an organisation with no theme", async () => {
    route(feed({ domains: [] }));
    render(<RfpWatchView {...props} />);
    expect(await screen.findByText("Tell us what KABIL works on")).toBeInTheDocument();
  });

  it("points to Funder Match when no call is open", async () => {
    route(feed({ items: [] }));
    render(<RfpWatchView {...props} />);
    expect(await screen.findByText("No open calls in Education, Health right now")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "See funders who fit you" }));
    expect(props.onFunderMatch).toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: /Saved/ }));
    expect(screen.getByText(/Save a call to keep it here/)).toBeInTheDocument();
  });

  it("reloads for another organisation", async () => {
    route(feed());
    render(<RfpWatchView {...props} />);
    await screen.findByRole("article", { name: "School libraries" });
    await userEvent.selectOptions(screen.getByRole("combobox", { name: /Organisation · all/ }), "seva");
    expect(call).toHaveBeenCalledWith("/api/rfps/feed?org=seva");
  });

  it("shows a member's one organisation, and someone with none", async () => {
    getMe.mockResolvedValue({ ...staff, is_staff: false, memberships: [{ org_id: 1, org_slug: "kabil", org_name: "KABIL", role: "steward" }] });
    route(feed());
    const { unmount } = render(<RfpWatchView {...props} />);
    expect(await screen.findByText("Your organisation")).toBeInTheDocument();
    unmount();
    getMe.mockResolvedValue({ ...staff, is_staff: false, memberships: [] });
    render(<RfpWatchView {...props} />);
    expect(await screen.findByText("RFP Watch works for an organisation")).toBeInTheDocument();
  });

  it("labels the picker for a steward of several", async () => {
    const memberships = ORGS.map((o) => ({ org_id: o.id, org_slug: o.slug, org_name: o.name, role: "steward" }));
    getMe.mockResolvedValue({ ...staff, is_staff: false, memberships });
    route(feed());
    render(<RfpWatchView {...props} />);
    expect(await screen.findByRole("combobox", { name: /2 you steward/ })).toBeInTheDocument();
  });

  it("shows a failed load", async () => {
    route(new Error("Feed down"));
    render(<RfpWatchView {...props} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Feed down");
  });
});

describe("daysLeft", () => {
  it("counts whole days, and none without a deadline", () => {
    expect(daysLeft("2026-10-25", new Date(2026, 9, 21))).toBe(4);
    expect(daysLeft(null)).toBeNull();
  });
});
