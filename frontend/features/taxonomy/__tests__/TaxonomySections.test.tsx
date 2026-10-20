import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { DomainSection, SharedSection } from "@/features/taxonomy/TaxonomySections";
import { LENSES } from "@/features/taxonomy/data";
import type { Domain } from "@/features/taxonomy/types";

const sub = (code: string, label: string, schemes: string[] = []) => ({
  code, label, sdgs: ["4"], csr: [{ clause: "ii", sector: "Education" }], schemes,
});

const domain: Domain = {
  domain: "education", label: "Education", status: "active", source: "From the NEP",
  themes: [
    { code: "ece", label: "Early childhood", sub_themes: [sub("creche", "Creches", ["ICDS", "Poshan"]), sub("pre", "Pre-school")] },
    { code: "sch", label: "Schooling", sub_themes: [sub("lib", "Libraries")] },
  ],
};

describe("DomainSection", () => {
  it("anchors the domain, counts its themes and opens only the first", () => {
    const { container } = render(<DomainSection domain={domain} />);
    expect(container.querySelector("section#education")).not.toBeNull();
    expect(screen.getByText("2 themes, 3 sub-themes. From the NEP.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Early childhood/ })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("button", { name: /Schooling/ })).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText("Creches")).toBeInTheDocument();
    expect(screen.queryByText("Libraries")).not.toBeInTheDocument();
  });

  it("shows a sub-theme's SDGs and crosswalks, with Schemes only when it has some", () => {
    render(<DomainSection domain={domain} />);
    const creches = screen.getByText("Creches").parentElement!;
    expect(within(creches).getByText(/^SDG 4 · /)).toBeInTheDocument();
    expect(within(creches).getByText("(ii) Education")).toBeInTheDocument();
    expect(within(creches).getByText("ICDS · Poshan")).toBeInTheDocument();
    expect(within(screen.getByText("Pre-school").parentElement!).queryByText("Schemes")).toBeNull();
  });

  it("toggles a theme open and closed", async () => {
    render(<DomainSection domain={domain} />);
    await userEvent.click(screen.getByRole("button", { name: /Schooling/ }));
    expect(screen.getByText("Libraries")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Early childhood/ }));
    expect(screen.queryByText("Creches")).not.toBeInTheDocument();
  });

  it("a draft domain with no themes shows only its source", () => {
    render(<DomainSection domain={{ ...domain, themes: [], source: "Not yet drafted" }} />);
    expect(screen.getByText("Not yet drafted.")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});

describe("SharedSection", () => {
  it("lists lenses, populations, SDGs and Schedule VII clauses in use", () => {
    const { container } = render(<SharedSection />);
    expect(container.querySelector("section#shared-vocabulary")).not.toBeNull();
    expect(screen.getByText(`Lenses (${LENSES.length})`)).toBeInTheDocument();
    expect(screen.getByText(/^Population groups \(\d+\)$/)).toBeInTheDocument();
    expect(screen.getByText("SDGs (17)")).toBeInTheDocument();
    expect(screen.getByText("Schedule VII in use")).toBeInTheDocument();
    const withSdg = LENSES.find((l) => l.adds_sdgs.length);
    if (withSdg) expect(screen.getByText(`${withSdg.label} · adds SDG ${withSdg.adds_sdgs.join(", ")}`)).toBeInTheDocument();
  });
});
