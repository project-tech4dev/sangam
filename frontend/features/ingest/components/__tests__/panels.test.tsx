import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ImportRun, ResearchRecord } from "../../lib/types";
import { EMPTY_SOURCES } from "../../lib/sourcePick";
import { queueItem, review, source, status, stubFetch } from "./fakes";

vi.mock("@/lib/api/auth-headers", () => ({ authHeaders: async () => ({}) }));

import { ImportThreads } from "../ImportThreads";
import { ProposalList } from "../ProposalList";
import { ResearchedRecently } from "../ResearchedRecently";
import { RunHistory } from "../RunHistory";
import { ScoutRail } from "../ScoutRail";
import { ScoutReply } from "../ScoutReply";
import { ScoutRunPanel } from "../ScoutRunPanel";
import { SourceGroups } from "../SourceGroups";
import { SourcePanel } from "../SourcePanel";
import { StepBar } from "../StepBar";
import { WaitingForYou } from "../WaitingForYou";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const record = (over: Partial<ResearchRecord> = {}): ResearchRecord => ({
  id: 1,
  entity_name: "kabil ltd",
  canonical_name: "KABIL",
  entity_kind: "funder",
  slug: "kabil",
  status: "ready",
  stopped_reason: null,
  summary: "",
  fact_count: 12,
  sources_read: [],
  not_found: [],
  researched_at: "2026-10-01T00:00:00Z",
  saved_at: null,
  resolved_org_id: null,
  resolved_funder_id: null,
  ...over,
});

describe("WaitingForYou", () => {
  const items = [queueItem(), queueItem({ id: 2, raw_name: "Pratham Edu", source: null, candidates: [{ id: 5, name: "Pratham", score: 1 }] }), queueItem({ id: 3, candidates: [] })];

  it("asks one question per close name and posts the answer", async () => {
    const fetchMock = stubFetch({ "/api/ingest/queue/1": { ok: true } });
    render(<WaitingForYou items={items} sources={[source()]} />);
    expect(screen.getByText("Is “Tata Trust” the same as “Tata Trusts”?")).toBeInTheDocument();
    expect(screen.getByText(/CSR Portal named it/)).toBeInTheDocument();
    expect(screen.getByText(/A source named it/)).toBeInTheDocument();
    await userEvent.click(screen.getAllByRole("button", { name: "Yes, the same" })[0]!);
    await waitFor(() => expect(screen.queryByText(/Tata Trust”/)).not.toBeInTheDocument());
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/api/ingest/queue/1"),
      expect.objectContaining({ method: "POST", body: JSON.stringify({ answer: "same", candidate_id: 9 }) }),
    );
  });

  it("drops a name on 'Not sure' without asking the backend, and hides when nothing is left", async () => {
    const fetchMock = stubFetch({});
    render(<WaitingForYou items={[items[1]!]} sources={[]} />);
    await userEvent.click(screen.getByRole("button", { name: "Not sure" }));
    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.queryByText("Waiting for you")).not.toBeInTheDocument();
  });

  it("keeps the question and says so when the answer is refused or fails", async () => {
    stubFetch({ "/queue/2": status(500) });
    const { unmount } = render(<WaitingForYou items={[items[1]!]} sources={[]} />);
    await userEvent.click(screen.getByRole("button", { name: "No, they're different" }));
    expect(await screen.findByText("Couldn't save your answer about “Pratham Edu”. Try again.")).toBeInTheDocument();
    unmount();
    stubFetch({ "/queue/2": new Error("offline") });
    render(<WaitingForYou items={[items[1]!]} sources={[]} />);
    await userEvent.click(screen.getByRole("button", { name: "No, they're different" }));
    expect(await screen.findByText(/Couldn't save your answer/)).toBeInTheDocument();
    expect(screen.getByText("Is “Pratham Edu” the same as “Pratham”?")).toBeInTheDocument();
  });

  it("renders nothing when no name has a candidate", () => {
    const { container } = render(<WaitingForYou items={[items[2]!]} sources={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("ResearchedRecently", () => {
  it("renders nothing with no research", () => {
    const { container } = render(<ResearchedRecently items={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows each row's state and links a saved one to its profile", () => {
    render(
      <ResearchedRecently
        items={[
          record({ saved_at: "2026-10-02", resolved_funder_id: 7, saved_by: "Asha", promotion_id: 3 }),
          record({ id: 2, canonical_name: null, entity_name: "Lost NGO", entity_kind: "org", status: "not_found" }),
        ]}
      />,
    );
    expect(screen.getByText(/Funder · 12 answers · .* · saved by Asha/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open profile" })).toHaveAttribute("href", "/registry/funders/7");
    expect(screen.getByText("Couldn't find it")).toBeInTheDocument();
    // Neither a saved row nor a not-found one can be reviewed, and only staff see undo or delete.
    expect(screen.queryByRole("button", { name: "Review & save" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Undo save|Delete/ })).not.toBeInTheDocument();
  });

  it("opens the review inline and reloads once saved", async () => {
    stubFetch({ "/review": review(), "/save": { slug: "kabil", entity: { kind: "funder", id: 1, name: "KABIL", status: null }, promotion_id: 1, written: 1, held: 0, reasons: [] } });
    const onChanged = vi.fn();
    render(<ResearchedRecently items={[record()]} onChanged={onChanged} />);
    await userEvent.click(screen.getByRole("button", { name: "Review & save" }));
    expect(screen.queryByRole("button", { name: "Review & save" })).not.toBeInTheDocument();
    await userEvent.click(await screen.findByRole("button", { name: "Save 1 organisation" }));
    await waitFor(() => expect(onChanged).toHaveBeenCalledOnce());
    expect(screen.queryByRole("region", { name: "Review before saving" })).not.toBeInTheDocument();
  });

  it("closes the review when declined", async () => {
    stubFetch({ "/review": review() });
    render(<ResearchedRecently items={[record()]} />);
    await userEvent.click(screen.getByRole("button", { name: "Review & save" }));
    await userEvent.click(await screen.findByRole("checkbox", { name: "Save KABIL" }));
    await userEvent.click(screen.getByRole("button", { name: "Continue without saving" }));
    expect(screen.queryByRole("region", { name: "Review before saving" })).not.toBeInTheDocument();
  });

  it("lets staff undo a save after confirming, and shows a refusal", async () => {
    const fetchMock = stubFetch({ "/promotions/3/undo": status(409, { detail: "A row was edited since" }) });
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValue(true);
    const onChanged = vi.fn();
    render(<ResearchedRecently items={[record({ saved_at: "x", promotion_id: 3 })]} staff onChanged={onChanged} />);
    await userEvent.click(screen.getByRole("button", { name: "Undo save" }));
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining("Undo saving KABIL?"));
    expect(fetchMock).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Undo save" }));
    expect(await screen.findByText("A row was edited since")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/api/ingest/promotions/3/undo"), expect.objectContaining({ method: "POST" }));
    expect(onChanged).not.toHaveBeenCalled();
  });

  it("lets staff delete unsaved research", async () => {
    const fetchMock = stubFetch({ "/research/kabil": { ok: true } });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const onChanged = vi.fn();
    render(<ResearchedRecently items={[record()]} staff onChanged={onChanged} />);
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(onChanged).toHaveBeenCalledOnce());
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/api/ingest/research/kabil"), expect.objectContaining({ method: "DELETE" }));
  });

  it("shows a few rows, then all on request", async () => {
    const items = Array.from({ length: 4 }, (_, i) => record({ id: i + 1, canonical_name: `Org ${i + 1}` }));
    render(<ResearchedRecently items={items} limit={2} />);
    expect(screen.queryByText("Org 3")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Show all (4)" }));
    expect(screen.getByText("Org 4")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Show fewer" }));
    expect(screen.queryByText("Org 4")).not.toBeInTheDocument();
  });
});

describe("SourcePanel and SourceGroups", () => {
  const sources = [
    source(),
    source({ key: "darpan", name: "NGO Darpan", host: "", access_rule: "no_scraping_manual_entry_allowed", categories: ["ngo"], dispatchable: false, has_adapter: false, basis: "Terms forbid", robots_checked_at: "2026-01-01" }),
    source({ key: "news", name: "News site", host: "news.in", access_rule: "weird_rule", categories: ["media"], has_adapter: false, basis: "Robots allow", yields: ["fcra"] }),
  ];

  it("filters by search, category and rule", async () => {
    render(<SourcePanel sources={sources} />);
    expect(screen.getByText(/3 registered, 1 with an adapter/)).toBeInTheDocument();
    expect(screen.getByText("checked per site")).toBeInTheDocument();
    expect(screen.getByText(/No scraping · ngo · checked 2026-01-01/)).toBeInTheDocument();
    expect(screen.getByText("pulls")).toBeInTheDocument();
    expect(screen.getByText("permitted")).toBeInTheDocument();
    expect(screen.getByText("held")).toBeInTheDocument();

    await userEvent.type(screen.getByPlaceholderText("Search name, host or reason…"), "fcra");
    expect(screen.getByText("1 of 3")).toBeInTheDocument();
    await userEvent.clear(screen.getByPlaceholderText("Search name, host or reason…"));

    await userEvent.click(screen.getByRole("button", { name: "ngo" }));
    expect(screen.getByText("1 of 3")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "All" }));
    await userEvent.click(screen.getByRole("button", { name: "weird_rule" }));
    expect(screen.getByText("News site")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "rfp" }));
    expect(screen.getByText("Nothing matches")).toBeInTheDocument();
  });

  it("groups sources by what Sangam may do with them", () => {
    render(<SourceGroups sources={sources} />);
    const group = (title: string) => screen.getByText(title).closest(".import-group") as HTMLElement;
    expect(within(group("Sangam reads these")).getByText("1")).toBeInTheDocument();
    expect(within(group("Allowed, not set up yet")).getByText("e.g. News site")).toBeInTheDocument();
    expect(within(group("Not allowed")).getByText("e.g. NGO Darpan")).toBeInTheDocument();
  });
});

describe("RunHistory and ProposalList", () => {
  const run: ImportRun = { id: 12, started_at: "2026-10-01T10:00:00Z", finished_at: null, status: "done", added: 3, updated: 1, matched: 2, queued: 1, failed: 1, refused: 0 };

  it("says when nothing has run, else lists runs", () => {
    const { unmount } = render(<RunHistory runs={[]} />);
    expect(screen.getByText(/No import has run yet/)).toBeInTheDocument();
    unmount();
    render(<RunHistory runs={[run, { ...run, id: 13, queued: 0, failed: 0 }]} />);
    expect(screen.getByText("#12")).toBeInTheDocument();
    expect(screen.getAllByText("3 added")).toHaveLength(2);
    expect(screen.getByText("1 queued")).toBeInTheDocument();
  });

  it("lists unclassified hosts, or nothing", () => {
    const { container, unmount } = render(<ProposalList items={[]} />);
    expect(container).toBeEmptyDOMElement();
    unmount();
    render(<ProposalList items={[{ id: 1, host: "x.org", first_seen_url: null, robots_result: "allowed", times_seen: 4, status: "new", first_seen_at: "", last_seen_at: "" }]} />);
    expect(screen.getByText("x.org")).toBeInTheDocument();
    expect(screen.getByText(/allowed · seen 4×/)).toBeInTheDocument();
  });
});

describe("ImportThreads", () => {
  const threads = [
    { id: "t1", title: "KABIL funding", createdAt: Date.parse("2026-10-05T00:00:00Z") },
    { id: "t2", title: "Pratham", createdAt: Date.parse("2026-10-02T00:00:00Z") },
    { id: "t3", title: "Older", createdAt: Date.parse("2026-09-10T00:00:00Z") },
  ];
  const props = { active: "t1", error: false, collapsed: false, onToggle: vi.fn(), onPick: vi.fn(), onNew: vi.fn() };

  it("groups chats by month and opens the one picked", async () => {
    const onPick = vi.fn();
    render(<ImportThreads {...props} threads={threads} onPick={onPick} />);
    expect(screen.getByText("October 2026")).toBeInTheDocument();
    expect(screen.getByText("September 2026")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /KABIL funding/ })).toHaveAttribute("aria-current", "page");
    await userEvent.click(screen.getByRole("button", { name: /Pratham/ }));
    expect(onPick).toHaveBeenCalledWith("t2");
  });

  it("shows loading, error and empty states", () => {
    const { rerender } = render(<ImportThreads {...props} threads={null} />);
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    rerender(<ImportThreads {...props} threads={null} error />);
    expect(screen.getByText("Couldn't load past imports.")).toBeInTheDocument();
    rerender(<ImportThreads {...props} threads={[]} />);
    expect(screen.getByText("No past chats yet.")).toBeInTheDocument();
  });

  it("collapses to two buttons", async () => {
    const onToggle = vi.fn();
    const onNew = vi.fn();
    const { rerender } = render(<ImportThreads {...props} threads={threads} onToggle={onToggle} onNew={onNew} />);
    await userEvent.click(screen.getByRole("button", { name: "Hide past imports" }));
    await userEvent.click(screen.getByRole("button", { name: "+ New chat" }));
    rerender(<ImportThreads {...props} threads={threads} collapsed onToggle={onToggle} onNew={onNew} />);
    expect(screen.queryByText("KABIL funding")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Show past chats" }));
    await userEvent.click(screen.getByRole("button", { name: "New chat" }));
    expect(onToggle).toHaveBeenCalledTimes(2);
    expect(onNew).toHaveBeenCalledTimes(2);
  });
});

describe("ScoutRail", () => {
  const access = { staff: false, stewardOf: ["A"], orgs: [{ slug: "a", name: "A" }] };
  const base = { sources: EMPTY_SOURCES, onSources: vi.fn(), readFrom: null, access, vaultFiles: [], staff: null };

  it("asks for sources before a research task starts", () => {
    const { rerender } = render(<ScoutRail {...base} started={false} task={null} />);
    expect(screen.getByText("Where Scout reads from")).toBeInTheDocument();
    rerender(<ScoutRail {...base} started={false} task="funder" />);
    expect(screen.getByText("Where should Scout read from?")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /Public websites/ })).toBeInTheDocument();
    // A fixed pull reads no chosen sources.
    rerender(<ScoutRail {...base} started={false} task="news" />);
    expect(screen.queryByText("Where should Scout read from?")).not.toBeInTheDocument();
  });

  it("says what a started run reads from, and shows staff the waiting names", () => {
    render(
      <ScoutRail
        {...base}
        started
        task="funder"
        readFrom="Public websites · Sangam's library"
        staff={{ sources: [], runs: [], queue: [queueItem()], proposals: [] }}
      />,
    );
    expect(screen.getByText("Public websites · Sangam's library")).toBeInTheDocument();
    expect(screen.getByText("Waiting for you")).toBeInTheDocument();
  });
});

describe("StepBar, ScoutReply and ScoutRunPanel", () => {
  it("marks steps done, now and to do", () => {
    render(<StepBar current={2} />);
    const items = screen.getAllByRole("listitem");
    expect(items.map((li) => li.getAttribute("data-state"))).toEqual(["done", "done", "now", "todo"]);
    expect(items[2]).toHaveAttribute("aria-current", "step");
    expect(screen.getAllByText("✓")).toHaveLength(2);
  });

  it("renders the reply as markdown, with safe outbound links and no raw HTML", () => {
    render(<ScoutReply text={"**Found** [site](https://kabil.org) [bad](javascript:alert(1)) <b>raw</b>\n\n| a |\n|---|\n| 1 |"} />);
    expect(screen.getByText("Found").tagName).toBe("STRONG");
    expect(screen.getByRole("link", { name: "site" })).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.getByText("bad").closest("a")?.getAttribute("href") ?? "").not.toMatch(/javascript/);
    expect(document.querySelector("b")).toBeNull();
    expect(screen.getByRole("table").parentElement).toHaveClass("scout-reply-scroll");
  });

  it("toggles its detail and blows it up to full size until Escape", async () => {
    const onToggle = vi.fn();
    const { rerender } = render(
      <ScoutRunPanel step={1} status="2 of 3 ready" action="Show progress" live open={false} onToggle={onToggle} tall={false}>
        <p>Board</p>
      </ScoutRunPanel>,
    );
    expect(screen.getByText("2 of 3 ready")).toBeInTheDocument();
    expect(screen.getByText("Board").parentElement).not.toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Show progress" }));
    expect(onToggle).toHaveBeenCalledOnce();
    rerender(
      <ScoutRunPanel step={1} status="s" action="Show progress" live={false} open onToggle={onToggle} tall>
        <p>Board</p>
      </ScoutRunPanel>,
    );
    expect(screen.getByRole("button", { name: "Close ✕" })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Open full size" }));
    expect(screen.getByRole("dialog", { name: "This run, full size" })).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Enter" });
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Open full size" }));
    await userEvent.click(screen.getAllByRole("button", { name: "Back to the chat" })[0]!);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Open full size" }));
    fireEvent.click(screen.getByRole("dialog").parentElement!);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("has no buttons when there is no detail", () => {
    render(
      <ScoutRunPanel step={0} status="Reading" action={null} live={false} open={false} onToggle={vi.fn()} tall={false}>
        <p>Board</p>
      </ScoutRunPanel>,
    );
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByText("Board")).not.toBeInTheDocument();
  });
});
