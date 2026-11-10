import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import { RegistryClient } from "@/features/registry/RegistryClient";
import { navigation } from "@/tests/setup";
import { registryRow } from "./fixtures";

// setUrlParams writes jsdom's history, which the shared setup does not reset.
afterEach(() => window.history.replaceState(null, "", "/"));

const rows = [
  registryRow({
    id: 1, slug: "kabil", name: "KABIL TRUST", populations: ["Children", "Women", "Farmers", "Youth"], sdgs: ["4"],
    themes: [
      { label: "Creches", domain: "Education" }, { label: "Schools", domain: "Education" },
      { label: "Libraries", domain: "Education" }, { label: "Tutoring", domain: "Education" },
      { label: "Misc", domain: "Others" }, { label: "Clinics", domain: "Health" },
    ],
    csr1: true, partners: 1, research_runs: 1, researched_on: "2026-10-12", search: "kabil dhubri",
  }),
  registryRow({ id: 2, slug: "seva", name: "Seva", states: ["Bihar"], place: "Bihar", fcra: true }),
  registryRow({
    kind: "funder", id: 3, slug: "tata", name: "Tata Trusts", funder_type: "foundation", place: null,
    states: ["Assam"], open_call: true, intake_mode: "invitation_only", themes: [{ label: "Clinics", domain: "Health" }],
    sdgs: ["3"], csr_prescribed: 2e7, csr_year: "FY2024",
  }),
];

const select = (name: string) => screen.getByRole("combobox", { name });
const names = () => screen.queryAllByRole("link").map((a) => a.querySelector(".reg-row-name")?.textContent);

describe("RegistryClient", () => {
  it("lists everyone with counts per bucket and links to each profile", () => {
    render(<RegistryClient rows={rows} />);
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
    render(<RegistryClient rows={rows} />);
    const kabil = screen.getByRole("link", { name: /Kabil Trust/ });
    const tags = [...kabil.querySelectorAll('[data-tone="theme"]')].map((t) => t.textContent);
    expect(tags).toEqual(["Education", "Health", "Others"]);
    expect(within(kabil).getByText("+1 more")).toBeInTheDocument();
    expect(within(kabil).getByTitle("SDG 4: Quality education")).toBeInTheDocument();
  });

  it("applies a theme filter from the URL, marks it moved and names the matching sub-themes", () => {
    navigation.search = new URLSearchParams("theme=Education");
    render(<RegistryClient rows={rows} />);
    expect(names()).toEqual(["Kabil Trust"]);
    expect(select("Theme")).toHaveAttribute("data-set", "true");
    expect(screen.getByText("1 match")).toBeInTheDocument();
    expect(screen.getByText("In Education:")).toBeInTheDocument();
    expect(screen.getByText("Creches · Schools · Libraries")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Kabil Trust/ }).querySelector('[data-active="true"]')).toHaveTextContent("Education");
  });

  it("puts the chosen population first in a row's Serves line", () => {
    navigation.search = new URLSearchParams("population=Youth");
    render(<RegistryClient rows={rows} />);
    const serves = [...screen.getByRole("link", { name: /Kabil Trust/ }).querySelectorAll('[data-tone="population"]')];
    expect(serves.map((s) => s.textContent)).toEqual(["Youth", "Children", "Women"]);
  });

  it("shows the CSO-only Registrations filter and filters by it", () => {
    navigation.search = new URLSearchParams("type=cso&reg=fcra");
    render(<RegistryClient rows={rows} />);
    expect(select("Registrations")).toHaveValue("fcra");
    expect(names()).toEqual(["Seva"]);
  });

  it("shows funder type and approach filters only for funders", () => {
    navigation.search = new URLSearchParams("type=funder&approach=open");
    render(<RegistryClient rows={rows} />);
    expect(select("Funder type")).toBeInTheDocument();
    const approach = select("How to approach");
    expect(within(approach).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "Any approach", "Open call now", "Invites partners",
    ]);
    expect(names()).toEqual(["Tata Trusts"]);
  });

  it("says so when nothing matches, and offers to clear", () => {
    navigation.search = new URLSearchParams("where=Sikkim&q=zzz");
    render(<RegistryClient rows={rows} />);
    expect(screen.getByText("No entries match these filters.")).toBeInTheDocument();
    expect(screen.getByText("0 match")).toBeInTheDocument();
    expect(screen.queryByText(/shown$/)).not.toBeInTheDocument();
  });

  it("writes a filter change to the address as a replace, dropping defaults", async () => {
    render(<RegistryClient rows={rows} />);
    await userEvent.selectOptions(select("Theme"), "Health");
    expect(new URLSearchParams(window.location.search).get("theme")).toBe("Health");
    await userEvent.selectOptions(select("Works in"), "ne");
    expect(new URLSearchParams(window.location.search).get("where")).toBe("ne");
    await userEvent.selectOptions(select("Theme"), "all");
    expect(new URLSearchParams(window.location.search).has("theme")).toBe(false);
  });

  it("writes every other filter under its own name", async () => {
    navigation.search = new URLSearchParams("type=funder");
    const { unmount } = render(<RegistryClient rows={rows} />);
    const param = (k: string) => new URLSearchParams(window.location.search).get(k);
    await userEvent.selectOptions(select("Who they serve"), "Women");
    await userEvent.selectOptions(select("SDG"), "3");
    await userEvent.selectOptions(select("Funder type"), "foundation");
    await userEvent.selectOptions(select("How to approach"), "invites");
    expect([param("population"), param("sdg"), param("ftype"), param("approach")]).toEqual(["Women", "3", "foundation", "invites"]);
    unmount();
    navigation.search = new URLSearchParams("type=cso");
    render(<RegistryClient rows={rows} />);
    await userEvent.selectOptions(select("Registrations"), "csr1");
    expect(param("reg")).toBe("csr1");
  });

  it("switching bucket resets the bucket-specific filters", async () => {
    window.history.replaceState(null, "", "/registry?reg=fcra");
    render(<RegistryClient rows={rows} />);
    await userEvent.click(screen.getByRole("button", { name: /Funders/ }));
    const params = new URLSearchParams(window.location.search);
    expect(params.get("type")).toBe("funder");
    expect(params.has("reg")).toBe(false);
  });

  it("filters as you type, and Clear filters empties the search", async () => {
    render(<RegistryClient rows={rows} />);
    const box = screen.getByRole("searchbox");
    await userEvent.type(box, "dhubri");
    expect(names()).toEqual(["Kabil Trust"]);
    expect(new URLSearchParams(window.location.search).get("q")).toBe("dhubri");
    await userEvent.click(screen.getByRole("button", { name: /Clear filters/ }));
    expect(box).toHaveValue("");
    expect(names()).toHaveLength(3);
  });

  it("shows twenty rows a page and the rest on request", async () => {
    const many = Array.from({ length: 25 }, (_, i) => registryRow({ id: i + 10, slug: `o${i}`, name: `Org${i}` }));
    render(<RegistryClient rows={many} />);
    expect(names()).toHaveLength(20);
    expect(screen.getByText("20 of 25 shown")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Show 5 more · 5 left" }));
    expect(names()).toHaveLength(25);
    expect(screen.getByText("End of the list")).toBeInTheDocument();
  });
});
