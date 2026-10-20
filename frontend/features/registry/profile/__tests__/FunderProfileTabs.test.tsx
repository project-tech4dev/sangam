import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FunderProfileTabs } from "@/features/registry/profile/FunderProfileTabs";
import { FunderMandate } from "@/features/registry/profile/FunderMandate";
import { FunderGiving, spendRows } from "@/features/registry/profile/FunderGiving";
import { FunderReach, latestFootprint } from "@/features/registry/profile/FunderReach";
import { ProfileHero } from "@/features/registry/profile/ProfileHero";
import { navigation } from "@/tests/setup";
import type { FootprintState, SpendLine } from "@/lib/api";
import { funderIdentity, funderProfile, group, metric, page, partnerLine, program } from "@/features/registry/__tests__/fixtures";

vi.mock("@/lib/api/auth-headers", () => ({ authHeaders: async () => ({}) }));

afterEach(() => window.history.replaceState(null, "", "/"));

describe("FunderProfileTabs", () => {
  it("opens on Mandate and writes a picked tab to the address", async () => {
    render(<FunderProfileTabs profile={funderProfile()} briefHref={null} />);
    expect(screen.getByText("No eligibility or open call recorded yet.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "Reach" }));
    expect(new URLSearchParams(window.location.search).get("tab")).toBe("reach");
    await userEvent.click(screen.getByRole("tab", { name: "Mandate" }));
    expect(new URLSearchParams(window.location.search).has("tab")).toBe(false);
  });

  it.each([
    ["giving", "No programme spend recorded yet."],
    ["reach", "No reach figures recorded yet."],
    ["news", "No posts tracked yet"],
    ["research", "No public documents on file yet."],
  ])("shows the %s tab's empty state", (tab, text) => {
    navigation.search = new URLSearchParams(`tab=${tab}`);
    render(<FunderProfileTabs profile={funderProfile()} briefHref={null} />);
    expect(screen.getByText(text)).toBeInTheDocument();
  });
});

describe("FunderMandate", () => {
  const base = { eligibility: [], openCalls: [], programs: [], hiddenContacts: 0 };

  it("shows empty states for a funder with nothing on file", () => {
    render(<FunderMandate funder={funderIdentity()} {...base} />);
    expect(screen.getByText("No identity facts recorded yet.")).toBeInTheDocument();
    expect(screen.getByText("No programmes recorded yet.")).toBeInTheDocument();
    expect(screen.getByText("No public contacts yet.")).toBeInTheDocument();
  });

  it("shows identity rows, the funder's eligibility wording, open calls and deduplicated contacts", () => {
    const funder = funderIdentity({
      funder_type: "csr", legal_form: "Section 8", founded_year: 1990, parent: { id: 1, name: "Tata Sons", slug: "tata-sons" },
      registered_address: "Mumbai", registered_location: "Maharashtra", cin: "U123", section_135_bound: true,
      intake_mode: "invitation_only", funds_external: false, grant_size_min: 1e5, grant_size_max: null,
      typical_duration_months: 24, aliases: ["TT"],
      contacts: [
        { id: 1, name: "A", role: "CSR head", kind: "person", email: "csr@t.org", phone: null, source_name: null, source_url: null },
        { id: 2, name: "B", role: "CSR head", kind: "person", email: "csr@t.org", phone: null, source_name: null, source_url: null },
        { id: 3, name: "Desk", role: null, kind: "office", email: null, phone: null, source_name: null, source_url: null },
      ],
    });
    render(
      <FunderMandate
        funder={funder}
        eligibility={[{ id: 1, title: null, content_md: "## Who can apply\n\nRegistered NGOs <b>only</b>.", source_name: null, source_url: "https://t.org/e" }]}
        openCalls={[
          { id: 1, title: "Water call", url: "https://t.org/call", deadline: "2026-11-30", amount_min: 1e5, amount_max: 1e6, source_url: null },
          { id: 2, title: "Offline call", url: "javascript:x", deadline: null, amount_min: null, amount_max: null, source_url: null },
        ]}
        programs={[program({ kind: "flagship_programme", source_url: "https://t.org/p" })]}
        hiddenContacts={1}
      />,
    );
    expect(screen.getByText("Section 8, formed 1990")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Tata Sons" })).toHaveAttribute("href", "/registry/funders/tata-sons");
    expect(screen.getByText("Mumbai · Maharashtra")).toBeInTheDocument();
    expect(screen.getByText("Bound by the CSR law")).toBeInTheDocument();
    expect(screen.getByText("invitation only")).toBeInTheDocument();
    expect(screen.getByText("No, runs its own work")).toBeInTheDocument();
    expect(screen.getByText("₹1 lakh – —")).toBeInTheDocument();
    expect(screen.getByText("24 months")).toBeInTheDocument();
    // A markdown h2 becomes a kicker, and raw HTML is dropped.
    expect(screen.getByText("Who can apply")).toHaveClass("card-kicker");
    expect(screen.queryByText("only")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Water call ↗" })).toHaveAttribute("href", "https://t.org/call");
    expect(screen.getByText("closes 30 Nov 2026")).toBeInTheDocument();
    expect(screen.getByText("Offline call").tagName).toBe("STRONG");
    expect(screen.queryByText("No open call found")).not.toBeInTheDocument();
    expect(screen.getByText("flagship programme")).toBeInTheDocument();
    expect(screen.getAllByText("CSR head")).toHaveLength(1);
    expect(screen.getByText("Desk")).toBeInTheDocument();
    expect(screen.getByText("1 named office-bearer is on file and not shown publicly.")).toBeInTheDocument();
  });

  it("says no open call was found when only eligibility is on file", () => {
    render(
      <FunderMandate funder={funderIdentity({ section_135_bound: false, funds_external: true })} {...base}
        eligibility={[{ id: 1, title: null, content_md: null, source_name: null, source_url: null }]} hiddenContacts={3} />,
    );
    expect(screen.getByText("No open call found")).toBeInTheDocument();
    expect(screen.getByText("Not bound by the CSR law")).toBeInTheDocument();
    expect(screen.getByText("Yes, through partner organisations")).toBeInTheDocument();
    expect(screen.getByText("3 named office-bearers are on file and not shown publicly.")).toBeInTheDocument();
  });
});

const spend = (over: Partial<SpendLine>): SpendLine => ({
  id: 1, program_id: null, program_name: null, fiscal_year: "FY2024", amount: 100000, notes: null,
  source_name: null, source_url: null, ...over,
});

describe("spendRows", () => {
  it("keeps a second line for the same programme and year as its own numbered row", () => {
    const rows = spendRows([
      spend({ id: 1, program_name: "Water" }), spend({ id: 2, program_name: "Water", fiscal_year: "FY2025" }),
      spend({ id: 3, program_name: "Water" }), spend({ id: 4 }), spend({ id: 5 }),
    ]);
    expect(rows.map((r) => r.label)).toEqual(["Water", "Water (2)", "Unnamed component 1", "Unnamed component 2"]);
    expect(rows[0].cells.size).toBe(2);
  });
});

describe("FunderGiving", () => {
  it("puts a programme's own total last when its components are listed", () => {
    render(
      <FunderGiving
        slug="tata"
        programs={[program({ id: 1, name: "Water" }), program({ id: 2, name: "Wells", parent_id: 1 })]}
        spend={[
          spend({ id: 1, program_id: 1, program_name: "Water", amount: 3e5, source_url: "https://t.org/ar", source_name: "Annual Report 2024" }),
          spend({ id: 2, program_id: 2, program_name: "Wells", amount: 1e5, source_url: "https://t.org/ar" }),
          spend({ id: 3, program_id: 2, program_name: "Wells", fiscal_year: "FY2023", amount: null }),
        ]}
        csrYears={[]} parent={null} partners={page([])}
      />,
    );
    const rows = screen.getAllByRole("row").slice(1);
    expect(rows.map((r) => r.querySelector("td")?.textContent)).toEqual(["Wells", "Total"]);
    expect(screen.getByRole("columnheader", { name: "Water" })).toBeInTheDocument();
    expect(within(rows[0]).getByText("—")).toBeInTheDocument();
    // Two lines from one source give one source chip.
    expect(screen.getAllByRole("link").filter((a) => a.getAttribute("href") === "https://t.org/ar")).toHaveLength(1);
    expect(screen.getByText("No CSR filings recorded yet.")).toBeInTheDocument();
    expect(screen.getByText("No partners recorded yet.")).toBeInTheDocument();
  });

  it("shows CSR years under the statutory filer and partners with a registry link", () => {
    render(
      <FunderGiving
        slug="tata" programs={[]} spend={[]} parent={{ id: 1, name: "Tata Sons", slug: "tata-sons" }}
        csrYears={[{ fiscal_year: "FY2024", prescribed_csr: null, total_spent: 2e7, spent_on_projects: null,
          unspent_transferred: null, local_area_spent: null, source_name: null, source_url: "https://www.mca.gov.in/c" }]}
        partners={page([
          group({ key: "a", name: "KABIL Trust", org_slug: "kabil", lines: [partnerLine({ id: 1, fy_is_dated: false, amount: null, project_name: null, program_name: "Creches" })] }),
          group({ key: "b", name: "Unlisted NGO", org_slug: null, lines: [] }),
        ], { total: 2, in_registry: 1, has_amounts: false })}
      />,
    );
    expect(screen.getByText("CSR by year · Tata Sons, the statutory filer")).toBeInTheDocument();
    expect(screen.getByText("not read")).toBeInTheDocument();
    expect(screen.getByText("₹2 crore")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "mca.gov.in ↗" })).toBeInTheDocument();
    expect(screen.getByText("1 in the Registry · no amounts published")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "KABIL Trust" })).toHaveAttribute("href", "/registry/kabil");
    expect(screen.getByText("Unlisted NGO").tagName).toBe("STRONG");
    expect(screen.getByText("undated")).toBeInTheDocument();
    expect(screen.getByText("Creches")).toBeInTheDocument();
  });
});

const fp = (over: Partial<FootprintState>): FootprintState => ({
  fiscal_year: "FY2024", state: "Assam", districts: 0, district_names: [], source_name: null, source_url: null, ...over,
});

describe("latestFootprint", () => {
  it("takes the newest year that names districts over a later states-only year", () => {
    const out = latestFootprint([
      fp({ fiscal_year: "FY2023", districts: 2 }), fp({ fiscal_year: "FY2023", state: "Bihar", districts: 1 }),
      fp({ fiscal_year: "FY2025", state: "Goa" }),
    ]);
    expect(out).toMatchObject({ year: "FY2023", districts: 3, states: 2 });
    expect(latestFootprint([fp({ fiscal_year: "FY2025" })]).year).toBe("FY2025");
    expect(latestFootprint([]).year).toBeNull();
  });
});

describe("FunderReach", () => {
  it("splits yearly figures from other periods and flags self-reported ones", () => {
    render(
      <FunderReach
        metrics={[
          metric({ id: 1, name: "Children", period: "FY2023-24", value: 500, stage: "output", unit: "people", place: "Assam" }),
          metric({ id: 2, name: "Children", period: "FY2024-25", value: null, target: 900, stage: "output", unit: "people",
            place: "Assam", source_url: "https://t.org/ar25", source_name: "AR 25" }),
          metric({ id: 3, name: "Wells", period: "since 2010", value: 40, stage: "impact", method: "self_reported" }),
          metric({ id: 4, name: "Acres", period: null, value: 7, stage: "unknown" }),
        ]}
        footprint={[]} stated={[]}
      />,
    );
    expect(screen.getByRole("columnheader", { name: "FY2024-25" })).toBeInTheDocument();
    expect(screen.getByText("target 900")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "AR 25 ↗" })).toBeInTheDocument();
    const other = screen.getByRole("columnheader", { name: "Totals and other periods" }).closest("table")!;
    const names = within(other).getAllByRole("row").slice(1).map((r) => r.querySelector("td")?.textContent);
    expect(names).toEqual(["Wells", "Acres"]);
    expect(within(other).getByText("since 2010")).toBeInTheDocument();
    expect(screen.getByText(/Self-reported; Sangam has not checked/)).toBeInTheDocument();
    expect(screen.getByText("No project places recorded yet.")).toBeInTheDocument();
    expect(screen.getByText("No stated geography recorded yet.")).toBeInTheDocument();
  });

  it("shows the latest year's places, older-year states with their year, and stated geography", () => {
    render(
      <FunderReach
        metrics={[]}
        footprint={[
          fp({ fiscal_year: "FY2024", districts: 2, district_names: ["DHUBRI", "GOALPARA"], source_url: "https://t.org/ar", source_name: "AR" }),
          fp({ fiscal_year: "FY2024", state: "Bihar", districts: 1 }),
          fp({ fiscal_year: "FY2022", state: "Goa" }), fp({ fiscal_year: "FY2021", state: "Goa" }),
        ]}
        stated={[
          { name: "KAMRUP", kind: "district", state: "Assam", role: "focus_area", note: "Floods", source_name: null, source_url: null },
          { name: "Sikkim", kind: "state", state: null, role: null, note: null, source_name: null, source_url: null },
        ]}
      />,
    );
    expect(screen.getByText("Where its projects are · FY2024")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("2 districts")).toBeInTheDocument();
    expect(screen.getByText("1 district")).toBeInTheDocument();
    expect(screen.getByText("Dhubri, Goalpara")).toBeInTheDocument();
    expect(screen.getByText("State only, no district named · FY2022")).toBeInTheDocument();
    expect(screen.getAllByText("Goa")).toHaveLength(1);
    expect(screen.getByRole("link", { name: "AR ↗" })).toBeInTheDocument();
    expect(screen.getByText("Kamrup")).toBeInTheDocument();
    expect(screen.getByText("focus area")).toBeInTheDocument();
    expect(screen.getByText("Floods")).toBeInTheDocument();
  });
});

describe("ProfileHero", () => {
  const tags = [
    { slug: "edu", label: "Creches", kind: "sub_theme", role: null, note: null, parent_label: "Education" },
    { slug: "kids", label: "Children", kind: "population", role: null, note: null, parent_label: null },
    { slug: "gender", label: "Women & girls", kind: "lens", role: null, note: null, parent_label: null },
  ];

  it("shows tags by kind, SDG tiles, the summary line, website and both CTAs", () => {
    render(
      <ProfileHero name="KABIL Trust" kicker="CSO" description="Creches in Assam." tags={tags}
        sdgs={[{ code: "4", label: "Education" }, { code: "99", label: "Made up" }]} whoLabel="Serves"
        line={["Assam", "since 2004"]} website="https://www.kabil.org/" ask={{ href: "/ask?org=kabil", label: "Ask about KABIL" }}
        brief="/registry/kabil/brief" />,
    );
    expect(screen.getByTitle("Education › Creches")).toHaveTextContent("Creches");
    expect(screen.getByText("Serves")).toBeInTheDocument();
    expect(screen.getByText("Women & girls")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "SDG 4: Quality education" })).toHaveAttribute("href", "https://sdgs.un.org/goals/goal4");
    expect(screen.getByRole("link", { name: "SDG 99: Made up" })).toBeInTheDocument();
    expect(screen.getByText(/Assam · since 2004 ·/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "kabil.org ↗" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ask about KABIL" })).toHaveAttribute("href", "/ask?org=kabil");
    expect(screen.getByRole("link", { name: "Read the research brief" })).toBeInTheDocument();
  });

  it("leaves out the facets, the line and the brief when there is nothing to show", () => {
    const { container } = render(
      <ProfileHero name="X" kicker="Funder" description={null} tags={[]} sdgs={[]} whoLabel="Funds" line={[]}
        website="not a url" ask={{ href: "/ask", label: "Ask" }} brief={null} />,
    );
    expect(container.querySelector(".profile-hero-facets")).toBeNull();
    expect(container.querySelector(".profile-hero-line")).toBeNull();
    expect(screen.queryByText("Read the research brief")).not.toBeInTheDocument();
  });
});
