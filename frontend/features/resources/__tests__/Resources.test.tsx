import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MethodologyArticle } from "@/features/resources/MethodologyArticle";
import { ResourcesShell } from "@/features/resources/ResourcesShell";
import { TaxonomyArticle } from "@/features/resources/TaxonomyArticle";
import { METHODOLOGY_SECTIONS } from "@/features/resources/tabs";
import { DOMAINS } from "@/features/taxonomy/data";

describe("ResourcesShell", () => {
  it("marks the current tab and indexes its sections beside the article", () => {
    render(<ResourcesShell tab="methodology"><MethodologyArticle /></ResourcesShell>);
    const nav = screen.getByRole("navigation", { name: "Resources" });
    expect(nav.querySelector('[aria-current="page"]')).toHaveTextContent("Methodology");
    expect(screen.getByRole("link", { name: "Taxonomy" })).toHaveAttribute("href", "/resources/taxonomy");
    expect(screen.getByRole("heading", { level: 2, name: /How the base is built/ })).toBeInTheDocument();
    // Every index entry has a section to jump to.
    for (const s of METHODOLOGY_SECTIONS) {
      expect(document.getElementById(s.id)).not.toBeNull();
      expect(screen.getByRole("heading", { level: 3, name: s.label })).toBeInTheDocument();
    }
  });

  it("the taxonomy tab shows a section for every domain and the shared vocabulary", () => {
    render(<ResourcesShell tab="taxonomy"><TaxonomyArticle /></ResourcesShell>);
    expect(screen.getByRole("navigation", { name: "Resources" }).querySelector('[aria-current="page"]')).toHaveTextContent("Taxonomy");
    for (const d of DOMAINS) expect(document.getElementById(d.domain)).not.toBeNull();
    expect(document.getElementById("shared-vocabulary")).not.toBeNull();
  });
});
