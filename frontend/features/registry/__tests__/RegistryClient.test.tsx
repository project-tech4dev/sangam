import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RegistryClient } from "@/features/registry/RegistryClient";
import type { RegistryPage, RegistryRow } from "@/lib/api";
import { navigation } from "@/tests/setup";
import { registryRow } from "./fixtures";

const fetchPage = vi.hoisted(() => vi.fn());
vi.mock("@/features/registry/api", () => ({ fetchRegistryPage: fetchPage }));

// setUrlParams writes jsdom's history, which the shared setup does not reset.
afterEach(() => window.history.replaceState(null, "", "/"));
beforeEach(() => {
  fetchPage.mockReset();
  fetchPage.mockImplementation(async () => page(rows)); // a pick asks the server at once
});

const rows = [
  registryRow({
    id: 1, slug: "kabil", name: "KABIL TRUST", populations: ["Children", "Women", "Farmers", "Youth"], sdgs: ["4"],
    themes: [
      { label: "Creches", domain: "Education" }, { label: "Schools", domain: "Education" },
      { label: "Libraries", domain: "Education" }, { label: "Tutoring", domain: "Education" },
      { label: "Misc", domain: "Others" }, { label: "Clinics", domain: "Health" },
    ],
    csr1: true, partners: 1, research_runs: 1, researched_on: "2026-10-12",
  }),
  registryRow({ id: 2, slug: "seva", name: "Seva", states: ["Bihar"], place: "Bihar", fcra: true }),
  registryRow({
    kind: "funder", id: 3, slug: "tata", name: "Tata Trusts", funder_type: "foundation", place: null,
    states: ["Assam"], open_call: true, intake_mode: "invitation_only", themes: [{ label: "Clinics", domain: "Health" }],
    sdgs: ["3"], csr_prescribed: 2e7, csr_year: "FY2024",
  }),
];

const opts = (...values: string[]) => values.map((value) => ({ value, count: 1 }));
// What the server sends: these items, counts and options over the whole Registry of the three rows above.
const page = (items: RegistryRow[], over: Partial<RegistryPage> = {}): RegistryPage => ({
  items, total: items.length, limit: 25, offset: 0, counts: { all: 3, org: 2, funder: 1 },
  facets: {
    theme: opts("Education", "Health", "Others"), population: opts("Children", "Women", "Farmers", "Youth"),
    sdg: opts("3", "4"), where: opts("Assam", "Bihar"), ftype: opts("foundation"), approach: opts("open", "invites"),
  },
  ...over,
});

const select = (name: string) => screen.getByRole("combobox", { name });
const names = () => screen.queryAllByRole("link").map((a) => a.querySelector(".reg-row-name")?.textContent);
const asked = () => Object.fromEntries(new URLSearchParams(fetchPage.mock.lastCall?.[0]));

describe("RegistryClient", () => {
  it("lists everyone with counts per bucket and links to each profile", () => {
    render(<RegistryClient first={page(rows)} />);
    expect(screen.getByRole("button", { name: /3\s*All/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: /2\s*CSOs/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /1\s*Funders/ })).toBeInTheDocument();
    expect(screen.getByText("3 in the Registry")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Kabil Trust/ })).toHaveAttribute("href", "/registry/kabil");
    expect(screen.getByRole("link", { name: /Tata Trusts/ })).toHaveAttribute("href", "/registry/funders/tata");
    expect(screen.getByText("Themes not tagged yet")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Clear filters/ })).not.toBeInTheDocument();
    // Only the bucket's own filters show: neither Registrations nor Funder type on All.
    expect(screen.queryByRole("combobox", { name: "Registrations" })).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Funder type" })).not.toBeInTheDocument();
  });

  it("orders a row's domains with Others last and caps the populations shown", () => {
    render(<RegistryClient first={page(rows)} />);
    const kabil = screen.getByRole("link", { name: /Kabil Trust/ });
    const tags = [...kabil.querySelectorAll('[data-tone="theme"]')].map((t) => t.textContent);
    expect(tags).toEqual(["Education", "Health", "Others"]);
    expect(within(kabil).getByText("+1 more")).toBeInTheDocument();
    expect(within(kabil).getByTitle("SDG 4: Quality education")).toBeInTheDocument();
  });

  it("applies a theme filter from the URL, marks it moved and names the matching sub-themes", () => {
    navigation.search = new URLSearchParams("theme=Education");
    render(<RegistryClient first={page([rows[0]])} />);
    expect(names()).toEqual(["Kabil Trust"]);
    expect(select("Theme")).toHaveAttribute("data-set", "true");
    expect(screen.getByText("1 match")).toBeInTheDocument();
    expect(screen.getByText("In Education:")).toBeInTheDocument();
    expect(screen.getByText("Creches · Schools · Libraries")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Kabil Trust/ }).querySelector('[data-active="true"]')).toHaveTextContent("Education");
  });

  it("puts the chosen population first in a row's Serves line", () => {
    navigation.search = new URLSearchParams("population=Youth");
    render(<RegistryClient first={page(rows)} />);
    const serves = [...screen.getByRole("link", { name: /Kabil Trust/ }).querySelectorAll('[data-tone="population"]')];
    expect(serves.map((s) => s.textContent)).toEqual(["Youth", "Children", "Women"]);
  });

  it("shows the CSO-only Registrations filter and filters by it", () => {
    navigation.search = new URLSearchParams("type=cso&reg=fcra");
    render(<RegistryClient first={page([rows[1]])} />);
    expect(select("Registrations")).toHaveValue("fcra");
    expect(names()).toEqual(["Seva"]);
  });

  it("shows funder type and approach filters only for funders", () => {
    navigation.search = new URLSearchParams("type=funder&approach=open");
    render(<RegistryClient first={page([rows[2]])} />);
    expect(select("Funder type")).toBeInTheDocument();
    const approach = select("How to approach");
    expect(within(approach).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "Any approach", "Open call now", "Invites partners",
    ]);
    expect(names()).toEqual(["Tata Trusts"]);
  });

  it("says so when nothing matches, and offers to clear", () => {
    navigation.search = new URLSearchParams("where=Sikkim&q=zzz");
    render(<RegistryClient first={page([])} />);
    expect(screen.getByText("No entries match these filters.")).toBeInTheDocument();
    expect(screen.getByText("0 match")).toBeInTheDocument();
    expect(screen.queryByText(/shown$/)).not.toBeInTheDocument();
  });

  it("writes a filter change to the address as a replace, dropping defaults", async () => {
    render(<RegistryClient first={page(rows)} />);
    await userEvent.selectOptions(select("Theme"), "Health");
    expect(new URLSearchParams(window.location.search).get("theme")).toBe("Health");
    await userEvent.selectOptions(select("Works in"), "ne");
    expect(new URLSearchParams(window.location.search).get("where")).toBe("ne");
    await userEvent.selectOptions(select("Theme"), "all");
    expect(new URLSearchParams(window.location.search).has("theme")).toBe(false);
  });

  it("writes every other filter under its own name", async () => {
    navigation.search = new URLSearchParams("type=funder");
    const { unmount } = render(<RegistryClient first={page(rows)} />);
    const param = (k: string) => new URLSearchParams(window.location.search).get(k);
    await userEvent.selectOptions(select("Who they serve"), "Women");
    await userEvent.selectOptions(select("SDG"), "3");
    await userEvent.selectOptions(select("Funder type"), "foundation");
    await userEvent.selectOptions(select("How to approach"), "invites");
    expect([param("population"), param("sdg"), param("ftype"), param("approach")]).toEqual(["Women", "3", "foundation", "invites"]);
    unmount();
    navigation.search = new URLSearchParams("type=cso");
    render(<RegistryClient first={page(rows)} />);
    await userEvent.selectOptions(select("Registrations"), "csr1");
    expect(param("reg")).toBe("csr1");
  });

  it("switching bucket resets the bucket-specific filters", async () => {
    window.history.replaceState(null, "", "/registry?reg=fcra");
    render(<RegistryClient first={page(rows)} />);
    await userEvent.click(screen.getByRole("button", { name: /Funders/ }));
    const params = new URLSearchParams(window.location.search);
    expect(params.get("type")).toBe("funder");
    expect(params.has("reg")).toBe(false);
  });

  it("asks the server once typing pauses, and Clear filters empties the search", async () => {
    fetchPage.mockResolvedValue(page([rows[0]]));
    render(<RegistryClient first={page(rows)} />);
    expect(fetchPage).not.toHaveBeenCalled();
    const box = screen.getByRole("searchbox");
    await userEvent.type(box, "dhubri");
    expect(new URLSearchParams(window.location.search).get("q")).toBe("dhubri");
    await waitFor(() => expect(names()).toEqual(["Kabil Trust"]));
    expect(fetchPage).toHaveBeenCalledTimes(1);
    expect(asked()).toEqual({ q: "dhubri", limit: "25", offset: "0" });
    fetchPage.mockResolvedValue(page(rows));
    await userEvent.click(screen.getByRole("button", { name: /Clear filters/ }));
    expect(box).toHaveValue("");
    await waitFor(() => expect(names()).toHaveLength(3));
  });

  it("asks once, with every filter, when a search is cleared with the filters", async () => {
    navigation.search = new URLSearchParams("theme=Health&q=dhubri");
    render(<RegistryClient first={page([rows[0]])} />);
    await userEvent.click(screen.getByRole("button", { name: /Clear filters/ }));
    await waitFor(() => expect(names()).toHaveLength(3));
    await new Promise((r) => setTimeout(r, 300)); // past the search delay: no second ask
    expect(fetchPage).toHaveBeenCalledTimes(1);
    expect(asked()).toEqual({ limit: "25", offset: "0" });
  });

  it("asks a dropdown pick at once, with the text typed so far", async () => {
    fetchPage.mockResolvedValue(page([rows[2]]));
    render(<RegistryClient first={page(rows)} />);
    await userEvent.type(screen.getByRole("searchbox"), "tata");
    await userEvent.selectOptions(select("Theme"), "Health");
    await waitFor(() => expect(asked()).toEqual({ theme: "Health", q: "tata", limit: "25", offset: "0" }));
    await new Promise((r) => setTimeout(r, 300));
    expect(fetchPage).toHaveBeenCalledTimes(1);
  });

  it("keeps the cards and dropdowns from the first page when a later page carries none", async () => {
    const many = Array.from({ length: 30 }, (_, i) => registryRow({ id: i + 10, slug: `o${i}`, name: `Org${i}` }));
    fetchPage.mockResolvedValue(page(many.slice(25), { total: 30, offset: 25, counts: {}, facets: {} }));
    render(<RegistryClient first={page(many.slice(0, 25), { total: 30 })} />);
    await userEvent.click(screen.getByRole("button", { name: "Show 5 more · 5 left" }));
    await waitFor(() => expect(names()).toHaveLength(30));
    expect(screen.getByRole("button", { name: /3\s*All/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /1\s*Funders/ })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Health" })).toBeInTheDocument();
    expect(screen.getByText("30 of 30 shown")).toBeInTheDocument();
    expect(screen.getByText("End of the list")).toBeInTheDocument();
  });

  it("shows the first 25 and asks the server for the next batch", async () => {
    const many = Array.from({ length: 30 }, (_, i) => registryRow({ id: i + 10, slug: `o${i}`, name: `Org${i}` }));
    fetchPage.mockResolvedValue(page(many.slice(25), { total: 30, offset: 25 }));
    render(<RegistryClient first={page(many.slice(0, 25), { total: 30 })} />);
    expect(names()).toHaveLength(25);
    expect(screen.getByText("25 of 30 shown")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Show 5 more · 5 left" }));
    await waitFor(() => expect(names()).toHaveLength(30));
    expect(asked()).toEqual({ limit: "25", offset: "25" });
    expect(screen.getByText("End of the list")).toBeInTheDocument();
  });
});
