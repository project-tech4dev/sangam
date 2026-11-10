import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SECTIONS } from "@/features/terms/sections";
import { TermsPage } from "@/features/terms/TermsPage";

describe("TermsPage", () => {
  it("numbers every section the index lists, each anchored for the index to jump to", () => {
    render(<TermsPage />);
    expect(screen.getByRole("heading", { level: 1, name: "Terms & Privacy" })).toBeInTheDocument();
    SECTIONS.forEach(([id, label], i) => {
      // The index may shorten a title, so only the number is held to the order.
      expect(document.getElementById(id)?.querySelector("h2")?.textContent).toMatch(new RegExp(`^${i + 1}\\. `));
      expect(screen.getAllByRole("link", { name: label }).some((a) => a.getAttribute("href") === `#${id}`)).toBe(true);
    });
  });
});
