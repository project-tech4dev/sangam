import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { MeOut, Story, StoryEntity, StoryPage } from "@/lib/api";

const call = vi.fn();
const getMe = vi.fn();
vi.mock("@/features/ask/lib/rest", () => ({ call: (...a: unknown[]) => call(...a), getMe: () => getMe() }));

import { MediaView } from "@/features/ask/views/media/MediaView";
import { StoryCard } from "@/features/ask/views/media/StoryCard";

const ORGS = [
  { slug: "kabil", name: "KABIL" },
  { slug: "seva", name: "Seva" },
];
const staff: MeOut = { id: "u", email: null, is_staff: true, is_anonymous: false, memberships: [] };
const member: MeOut = { ...staff, is_staff: false, memberships: [{ org_id: 1, org_slug: "kabil", org_name: "KABIL", role: "member" }] };

const entity = (over: Partial<StoryEntity> = {}): StoryEntity => ({
  kind: "org", id: 1, slug: "kabil", name: "KABIL", stance: "negative", visibility: "public", match_level: "High", confidence_level: "Low",
  ...over,
});
const story = (row_id: number, headline: string, over: Partial<Story> = {}): Story => ({
  id: row_id, headline, headline_generated: false, summary: `${headline} summary`, published_on: "2026-10-01", content_kind: null,
  is_news: true, scope: null, topic: "fcra", sentiment: "positive", main_url: "https://news.example/a", main_host: "news.example",
  source_type: "news", visibility: null, match_level: "High", confidence_level: "Medium", channel: "press", also: [],
  entities: [entity()], places: ["Assam"], area_reason: null, row_id, about: null,
  ...over,
});
const page = (items: Story[], over: Partial<StoryPage> = {}): StoryPage => ({
  items, next_cursor: null, counts: { org: items.length, funder: 600, general: 3 }, last_pull: "2026-10-20T00:00:00Z", ...over,
});

const lastPath = () => call.mock.lastCall![0] as string;

beforeEach(() => getMe.mockResolvedValue(staff));
afterEach(() => vi.clearAllMocks());

describe("MediaView", () => {
  it("asks for the stories without a second /api/me when the page already knows who is signed in", async () => {
    call.mockResolvedValue(page([story(1, "KABIL wins award")]));
    render(<MediaView orgs={ORGS} me={staff} />);
    expect(await screen.findByText("KABIL wins award")).toBeInTheDocument();
    expect(getMe).not.toHaveBeenCalled();
  });

  it("lists the organisations' stories with the bucket counts", async () => {
    call.mockResolvedValue(page([story(1, "KABIL wins award")]));
    render(<MediaView orgs={ORGS} />);
    expect(await screen.findByText("KABIL wins award")).toBeInTheDocument();
    expect(lastPath()).toBe("/api/news/stories?bucket=org&since=30d&limit=10&area=all");
    expect(screen.getByText(/Last pull/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^500\+\s*Funders/ })).toBeInTheDocument();
    expect(screen.getByText("1 story · strongest match first")).toBeInTheDocument();
    expect(screen.getByText("Every cohort organisation")).toBeInTheDocument();
  });

  it("sends the filters and search with the request", async () => {
    call.mockResolvedValue(page([]));
    render(<MediaView orgs={ORGS} />);
    await screen.findByText(/Nothing here with these filters/);
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Organisation" }), "seva");
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Sentiment" }), "negative");
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Source" }), "social");
    await userEvent.type(screen.getByRole("searchbox"), "flood");
    await waitFor(() => expect(lastPath()).toContain("q=flood"));
    expect(lastPath()).toContain("org=seva");
    expect(lastPath()).toContain("sentiment=negative");
    expect(lastPath()).toContain("source=social");
    expect(screen.getByText(/matching "flood"/)).toBeInTheDocument();
  });

  it("switches to General with its area and topic filters", async () => {
    call.mockResolvedValue(page([story(2, "FCRA rule change", { area_reason: "North East", entities: [] })]));
    render(<MediaView orgs={ORGS} />);
    await screen.findByText("FCRA rule change");
    await userEvent.click(screen.getByRole("button", { name: /General/ }));
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Topic" }), "csr_funding");
    await waitFor(() => expect(lastPath()).toContain("topic=csr_funding"));
    expect(lastPath()).toContain("bucket=general");
    expect(screen.getByText("North East")).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "My area" })).toBeNull();
  });

  it("lets staff hide a wrong match", async () => {
    const funder = entity({ kind: "funder", id: 9, slug: "axis", name: "Axis" });
    call.mockImplementation(async (path: string) =>
      path.includes("/hide") ? {} : page([story(3, "Axis CSR spend", { about: funder })]),
    );
    render(<MediaView orgs={ORGS} />);
    await userEvent.click(screen.getByRole("button", { name: /Funders/ }));
    await userEvent.click(await screen.findByRole("button", { name: "Hide: wrong match" }));
    expect(call).toHaveBeenCalledWith("/api/news/stories/3/hide", "POST", { funder_id: 9 });
    await waitFor(() => expect(screen.queryByText("Axis CSR spend")).toBeNull());
  });

  it("tells a member with no organisation, and asks nothing of the server", async () => {
    getMe.mockResolvedValue({ ...staff, is_staff: false });
    call.mockResolvedValue(page([]));
    render(<MediaView orgs={ORGS} />);
    expect(await screen.findByText("No organisation linked to your account")).toBeInTheDocument();
    expect(call).not.toHaveBeenCalled();
  });

  it("defaults a member's General area to theirs", async () => {
    getMe.mockResolvedValue(member);
    call.mockResolvedValue(page([], { last_pull: null, counts: null }));
    render(<MediaView orgs={ORGS} />);
    expect(await screen.findByText(/No news pulled yet/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^–\s*My organisations/ })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /General/ }));
    await waitFor(() => expect(lastPath()).toContain("area=mine"));
    expect(screen.queryByRole("button", { name: /Hide/ })).toBeNull();
  });

  it("shows a failed load", async () => {
    call.mockRejectedValue(new Error("News down"));
    render(<MediaView orgs={ORGS} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("News down");
  });
});

describe("StoryCard", () => {
  it("leads with the entity and its stance in a bucket, with copies folded in", () => {
    const s = story(1, "Story", {
      also: [{ url: "https://b.example/x", host: "b.example", source_type: "news" }],
      headline_generated: true,
      main_url: null,
      published_on: null,
    });
    render(<StoryCard story={s} about="org" />);
    expect(screen.getByRole("link", { name: "KABIL" })).toHaveAttribute("href", "/registry/kabil");
    expect(screen.getByText("Negative")).toBeInTheDocument();
    expect(screen.getByText("On public profile")).toBeInTheDocument();
    expect(screen.getByText(/Headline written by Sangam · No date · Assam/)).toBeInTheDocument();
    expect(screen.getByText("Also reported in 1 more")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "b.example" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Story" })).toBeNull();
  });

  it("names each entity on its hide button when there are several, and hides scores signed out", async () => {
    const onHide = vi.fn();
    const two = [entity(), entity({ id: 2, slug: "seva", name: "Seva" })];
    const { unmount } = render(<StoryCard story={story(1, "Two", { entities: two })} about="org" onHide={onHide} />);
    await userEvent.click(screen.getByRole("button", { name: "Hide: wrong match (Seva)" }));
    expect(onHide).toHaveBeenCalledWith(two[1]);
    unmount();
    render(<StoryCard story={story(1, "Signed out", { topic: "mystery" })} signedIn={false} />);
    const card = screen.getByText("Signed out").closest("article")!;
    expect(within(card).getByText("mystery")).toBeInTheDocument();
    expect(within(card).getByText("Positive")).toBeInTheDocument();
    expect(within(card).queryByText("Match")).toBeNull();
  });
});
