import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { OrgProfileTabs } from "@/features/registry/profile/OrgProfileTabs";
import { OrgOverview } from "@/features/registry/profile/OrgOverview";
import { OrgPlaces } from "@/features/registry/profile/OrgPlaces";
import { OrgFunding } from "@/features/registry/profile/OrgFunding";
import { ResearchSources } from "@/features/registry/profile/ResearchSources";
import { navigation } from "@/tests/setup";
import {
  group, identifier, orgIdentity, orgProfile, page, partnerLine, program, story,
} from "@/features/registry/__tests__/fixtures";

vi.mock("@/lib/api/auth-headers", () => ({ authHeaders: async () => ({}) }));

afterEach(() => window.history.replaceState(null, "", "/"));

const open = (tab: string) => (navigation.search = new URLSearchParams(tab ? `tab=${tab}` : ""));

describe("OrgProfileTabs", () => {
  it("opens on Overview and writes a picked tab to the address", async () => {
    render(<OrgProfileTabs profile={orgProfile()} name="KABIL Trust" briefHref={null} />);
    expect(screen.getByText("No identity facts recorded yet.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "Funding" }));
    expect(new URLSearchParams(window.location.search).get("tab")).toBe("funding");
  });

  it.each([
    ["work", "No places recorded yet."],
    ["funding", "No funders named yet."],
    ["news", "No press coverage found"],
    ["research", "No research has been run yet."],
  ])("shows the %s tab's empty state rather than a blank tab", (tab, text) => {
    open(tab);
    render(<OrgProfileTabs profile={orgProfile()} name="KABIL Trust" briefHref={null} />);
    expect(screen.getByText(text)).toBeInTheDocument();
  });
});

describe("OrgOverview", () => {
  it("shows empty states for an org with nothing on file", () => {
    render(<OrgOverview org={orgIdentity()} hiddenContacts={0} />);
    expect(screen.getByText("No identity facts recorded yet.")).toBeInTheDocument();
    expect(screen.getByText("No registrations on file yet.")).toBeInTheDocument();
    expect(screen.getByText("No public contact details yet.")).toBeInTheDocument();
  });

  it("shows identity, the strongest registration per type, contacts and hidden contacts", () => {
    const org = orgIdentity({
      legal_form: "Trust", registration_date: "2004-03-01", aliases: ["KABIL", "Kabil Foundation"],
      parent: { id: 9, name: "Parent Org", slug: "parent" }, staff_count: 40, staff_count_note: "2024 report",
      source_url: "https://ngodarpan.gov.in/x", registered_address: "Dhubri, Assam", website: "https://www.kabil.org/",
      identifiers: [
        identifier({ id_type: "fcra", status: "applied", id_value: null, application_ref: "A-9", source_type: "org_document", evidence: "claimed" }),
        identifier({ id_type: "pan", source_type: "aggregator", id_value: "OLD", is_current: false }),
        identifier({ id_type: "pan", source_type: "registry", evidence: "verified", source_url: "https://incometax.gov.in/p" }),
        identifier({ id_type: "80g", status: "expired", id_value: null, number_withheld: true }),
        identifier({ id_type: "custom_id", status: "registered", id_value: "Z1" }),
      ],
      contacts: [{ id: 1, name: "Asha", role: "Director", kind: "person", email: "a@k.org", phone: "123", source_name: null, source_url: null }],
    });
    render(<OrgOverview org={org} hiddenContacts={2} />);
    expect(screen.getByText("March 2004")).toBeInTheDocument();
    expect(screen.getByText("KABIL · Kabil Foundation")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Parent Org" })).toHaveAttribute("href", "/registry/parent");
    expect(screen.getByText("40 — 2024 report")).toBeInTheDocument();
    expect(screen.getByText("Registrations · 4")).toBeInTheDocument();
    // The current registry PAN wins over an old aggregator one.
    expect(screen.getByText("AAATK1234K")).toBeInTheDocument();
    expect(screen.queryByText("OLD")).not.toBeInTheDocument();
    expect(screen.getByText("verified by government registry")).toBeInTheDocument();
    expect(screen.getByText("application A-9")).toBeInTheDocument();
    expect(screen.getByText("on file, not published")).toBeInTheDocument();
    expect(screen.getByText("custom_id")).toBeInTheDocument();
    expect(screen.getByText("Dhubri, Assam")).toBeInTheDocument();
    expect(screen.getByText("a@k.org")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "kabil.org ↗" })).toHaveAttribute("href", "https://www.kabil.org/");
    expect(screen.getByText("2 office-bearers are on file and not shown publicly.")).toBeInTheDocument();
  });

  it("a javascript: website is not linked", () => {
    render(<OrgOverview org={orgIdentity({ website: "javascript:alert(1)" })} hiddenContacts={1} />);
    expect(screen.queryByText("Website")).not.toBeInTheDocument();
    expect(screen.getByText("1 office-bearer is on file and not shown publicly.")).toBeInTheDocument();
  });
});

describe("OrgPlaces", () => {
  const place = (over = {}) => ({
    location_id: 1, kind: "district", name: "DHUBRI", state: "Assam", role: "works_in", note: null, program_id: null,
    program_name: null, source_name: null, source_url: null, ...over,
  });

  it("groups districts under their state, counts them, and names the office", () => {
    render(
      <OrgPlaces
        places={[
          place(), place({ location_id: 2, name: "Goalpara", program_name: "Creches", note: "since 2019" }),
          place({ location_id: 3, kind: "state", name: "Meghalaya", state: null, note: "Statewide." }),
          place({ location_id: 4, kind: "district", name: "Guwahati", role: "registered" }),
        ]}
        programs={[]}
      />,
    );
    expect(screen.getByText("Dhubri")).toBeInTheDocument();
    expect(screen.getByText("Creches · since 2019")).toBeInTheDocument();
    expect(screen.getByText("State only, no district named. Statewide.")).toBeInTheDocument();
    expect(screen.getByText("Registered office · Guwahati")).toBeInTheDocument();
    expect(screen.getByText("No programmes recorded yet.")).toBeInTheDocument();
  });

  it("draws programmes as a tree with their metrics", () => {
    render(
      <OrgPlaces
        places={[]}
        programs={[
          program({ id: 1, name: "Early years", status: "active", start_date: "2020-06-01", description: "Creches.",
            source_url: "https://kabil.org/p",
            metrics: [
              { ...metricRow, id: 1, value: 1200, unit: "children", name: "reached" },
              { ...metricRow, id: 2, value: null, target: 50, unit: "creches", name: "planned" },
              { ...metricRow, id: 3, value: null, target: null, unit: "staff", name: "trained" },
            ] }),
          program({ id: 2, name: "Phase 2", parent_id: 1 }),
          program({ id: 3, name: "Orphan", parent_id: 99 }),
        ]}
      />,
    );
    expect(screen.getByText("Programmes · 3")).toBeInTheDocument();
    expect(screen.getByText("Phase 2").closest(".profile-line")).toHaveClass("profile-indent");
    expect(screen.getByText("Orphan").closest(".profile-line")).not.toHaveClass("profile-indent");
    expect(screen.getByText("from Jun 2020")).toBeInTheDocument();
    expect(screen.getByText("1,200")).toBeInTheDocument();
    expect(screen.getByText("creches (target)")).toBeInTheDocument();
    expect(screen.getByText("not stated")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "kabil.org ↗" })).toBeInTheDocument();
  });
});

const metricRow = {
  id: 0, name: "", value: null, target: null, unit: null, period: null, stage: null, method: null, program_id: null,
  place: null, source_name: null, source_url: null,
};

describe("OrgFunding", () => {
  it("lists funders by group, flags an unconfirmed link, and shows the financials table", () => {
    const funders = page([
      group({ lines: [
        partnerLine({ id: 1, relationship_status: "unconfirmed", notes: "Creche grant\nmore" }),
        partnerLine({ id: 2, fy_is_dated: false, amount: null, project_name: "Other", source_url: null }),
      ] }),
    ], { total: 3, next_cursor: "c" });
    render(
      <OrgFunding slug="kabil" name="KABIL Trust" funders={funders} financials={[
        { fiscal_year: "FY2024", total_income: 2e7, program_spend: 1.5e5, non_program_spend: null,
          foreign_contribution: 900, foreign_unspent: null, is_audited: true,
          source_name: "Annual Report 2023-24", source_url: "https://kabil.org/ar.pdf" },
      ]} />,
    );
    expect(screen.getByText(/stays unconfirmed until the funder's own record names KABIL Trust/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Tata Trusts" })).toHaveAttribute("href", "/registry/funders/tata-trusts");
    expect(screen.getByText("Creche grant")).toBeInTheDocument();
    expect(screen.getByText("undated")).toBeInTheDocument();
    expect(screen.getByText("₹5 lakh")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Show 2 more/ })).toBeInTheDocument();
    const row = screen.getByRole("row", { name: /FY2024/ });
    expect(within(row).getByText("FY2024 · audited")).toBeInTheDocument();
    expect(within(row).getByText("₹2 crore")).toBeInTheDocument();
    expect(within(row).getByText("—")).toBeInTheDocument();
    expect(within(row).getByRole("link", { name: "AR 2023-24 ↗" })).toBeInTheDocument();
  });

  it("says when no figures were found", () => {
    render(<OrgFunding slug="k" name="K" funders={page([])} financials={[]} />);
    expect(screen.getByText("No figures found for any year.")).toBeInTheDocument();
  });
});

describe("ResearchSources", () => {
  it("lists documents with what they back, and every readable source", () => {
    render(
      <ResearchSources
        briefHref="/registry/kabil/brief"
        documents={[
          { id: 1, title: "Annual report", doc_type: null, as_of: "FY2024", source_name: null, source_url: "https://kabil.org/ar.pdf",
            links: [{ program_id: 1, program_name: "Creches", fiscal_year: "FY2024", pages: ["3", "4"] },
              { program_id: 1, program_name: "Creches", fiscal_year: "FY2024", pages: ["3", "4"] }] },
          { id: 2, title: null, doc_type: null, as_of: null, source_name: null, source_url: "https://www.mca.gov.in/x", links: [] },
          { id: 3, title: null, doc_type: null, as_of: null, source_name: null, source_url: null, links: [] },
        ]}
        research={{ runs: 1, latest: null, sources: [
          { url: "https://give.do/kabil", first_read: "2026-10-12" },
          { url: "https://x.org/org-grant-intelligence/k", first_read: null },
          { url: "kabil site (no result)", first_read: null },
          { url: "ftp://x.org/a", first_read: null },
        ] }}
      />,
    );
    expect(screen.getByRole("link", { name: "Read the full brief →" })).toHaveAttribute("href", "/registry/kabil/brief");
    expect(screen.getByText("Backs Creches · FY2024 · 3, 4")).toBeInTheDocument();
    expect(screen.getByText("mca.gov.in")).toBeInTheDocument();
    expect(screen.getByText("Untitled document")).toBeInTheDocument();
    expect(screen.getByText("Every source read · 2")).toBeInTheDocument();
    expect(screen.getByText("aggregator")).toBeInTheDocument();
    expect(screen.getByText("earlier research")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Sangam's earlier research ↗" })).toBeInTheDocument();
    expect(screen.getByText("first read 12 Oct 2026")).toBeInTheDocument();
  });

  it("shows empty states without a brief link", () => {
    render(<ResearchSources documents={[]} research={{ runs: 0, latest: null, sources: [] }} briefHref={null} />);
    expect(screen.getByText("No public documents on file yet.")).toBeInTheDocument();
    expect(screen.queryByText(/full brief/)).not.toBeInTheDocument();
  });
});

describe("NewsSocial on an org", () => {
  it("lists press with its other reporters and groups posts by platform under a month chart", () => {
    renderNews([
          story({ also: [{ url: "https://b.example/x", host: "b.example", source_type: "press" }], summary: "Ten new creches." }),
          story({ row_id: 2, main_url: null, headline: "Unlinked story", published_on: "2026-08" }),
          story({ row_id: 3, channel: "social", source_type: "LinkedIn", headline: "Post one", published_on: "2026-09-01" }),
          story({ row_id: 4, channel: "social", source_type: "LinkedIn", headline: "Post two", main_url: null, published_on: "2026-01-20", summary: "s" }),
          story({ row_id: 5, channel: "social", source_type: null, main_host: "mastodon.social", headline: "Toot", published_on: null }),
    ]);
    expect(screen.getByRole("link", { name: "Creches open in Dhubri ↗" })).toHaveAttribute("href", "https://news.example/a");
    expect(screen.getByText("Ten new creches.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "b.example ↗" })).toBeInTheDocument();
    expect(screen.getByText("Unlinked story")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Posts found per month, April to September 2026: 0, 0, 0, 0, 0, 1" })).toBeInTheDocument();
    expect(screen.getByText("Li")).toBeInTheDocument();
    expect(screen.getByText("2 posts")).toBeInTheDocument();
    expect(screen.getByText("1 post")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Post one/ })).toBeInTheDocument();
  });

  it("explains an org whose only stories are its own posts", () => {
    renderNews([], { press: 0, social: 3, posts_since: null });
    expect(screen.getByText("Everything the news pulls found for KABIL Trust was its own social posts.")).toBeInTheDocument();
  });

  it("explains an org with no stories at all", () => {
    renderNews([], { press: 0, social: 0, posts_since: null });
    expect(screen.getByText("No stories about KABIL Trust clear the public bar yet.")).toBeInTheDocument();
    expect(screen.getByText("No posts tracked yet")).toBeInTheDocument();
  });
});

// The News tab rendered through OrgProfileTabs, so the tab wiring is exercised too.
function renderNews(stories: ReturnType<typeof story>[], counts = { press: 2, social: 3, posts_since: null as string | null }) {
  navigation.search = new URLSearchParams("tab=news");
  return render(<OrgProfileTabs profile={orgProfile({ news: stories, stories: counts })} name="KABIL Trust" briefHref={null} />);
}
