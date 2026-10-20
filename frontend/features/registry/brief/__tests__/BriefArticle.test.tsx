import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { BriefArticle } from "@/features/registry/brief/BriefArticle";
import type { Brief } from "@/features/registry/brief/parseBrief";
import { PrintButton } from "@/features/registry/brief/PrintButton";

const brief = (over: Partial<Brief> = {}): Brief => ({
  name: "Tata Trusts", summary: "A trust.", goals: [], sections: [], sources: [], ...over,
});

describe("BriefArticle", () => {
  it("lays out a funder brief: crumbs, meta, the ten fields, findings and sources", () => {
    render(
      <BriefArticle
        slug="tata"
        brief={brief({
          researched: "2026-10-12", status: "partial", website: "https://www.tata.org",
          summary: "Funds water. TEN FIELDS: (1) Water (2) Assam only",
          goals: ["Open calls"],
          sections: [
            { id: "programmes", title: "Programmes", findings: [
              { headlines: ["Assam", "Wells"], year: "FY2024", basis: "reported", evidence: "Dug 40 wells.",
                source: { name: "Annual report", url: "https://tata.org/ar", confidence: "high" },
                details: [{ label: "Themes", value: "Water" }] },
              { headlines: ["Board"], basis: "stated", evidence: "", source: { name: "Board page", url: "javascript:x", confidence: "" } },
              { headlines: ["Year only"], year: "FY2023", evidence: "" },
            ] },
            { id: "notes", title: "Notes", findings: [], text: "See [site](https://tata.org) and [bad](javascript:alert(1))." },
          ],
          notFound: "CSR-1", sources: ["https://tata.org/ar"],
        })}
      />,
    );
    expect(screen.getByRole("link", { name: "Funders" })).toHaveAttribute("href", "/registry?type=funder");
    expect(screen.getByRole("link", { name: "Tata Trusts" })).toHaveAttribute("href", "/registry/funders/tata");
    expect(screen.getByText("Researched 2026-10-12")).toBeInTheDocument();
    expect(screen.getByText("partial")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "tata.org" })).toBeInTheDocument();
    expect(screen.getByText("Funds water.")).toBeInTheDocument();
    expect(screen.getAllByRole("listitem").slice(0, 2).map((li) => li.textContent)).toEqual(["Water", "Assam only"]);
    expect(screen.getByText("What it set out to find (1)")).toBeInTheDocument();
    expect(screen.getByText("Dug 40 wells.").tagName).toBe("BLOCKQUOTE");
    expect(screen.getByRole("link", { name: "Annual report ↗" })).toHaveAttribute("href", "https://tata.org/ar");
    // A source whose URL is not http(s) is named but never linked.
    expect(screen.getByText("Board page").tagName).toBe("SPAN");
    expect(screen.getByText("Themes:")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "site" })).toHaveAttribute("href", "https://tata.org/");
    expect(screen.getByText("bad").closest("a")).not.toHaveAttribute("href");
    expect(screen.getByText("CSR-1")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "https://tata.org/ar" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Gaps and sources" })).toBeInTheDocument();
  });

  it("an org brief links back to CSOs, and a plain summary stays one paragraph", () => {
    render(<BriefArticle slug="kabil" kind="org" brief={brief({ name: "KABIL", summary: "TEN FIELDS: only one", status: "odd" })} />);
    expect(screen.getByRole("link", { name: "CSOs" })).toHaveAttribute("href", "/registry?type=cso");
    expect(screen.getByRole("link", { name: "KABIL" })).toHaveAttribute("href", "/registry/kabil");
    expect(screen.getByText("TEN FIELDS: only one")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Gaps and sources" })).not.toBeInTheDocument();
  });
});

describe("PrintButton", () => {
  it("prints under the brief's title, then restores the page title", async () => {
    const print = vi.spyOn(window, "print").mockImplementation(() => {
      expect(document.title).toBe("Tata — research brief");
    });
    document.title = "Sangam";
    render(<PrintButton title="Tata — research brief" />);
    await userEvent.click(screen.getByRole("button", { name: "Download PDF" }));
    expect(print).toHaveBeenCalledOnce();
    expect(document.title).toBe("Sangam");
    print.mockRestore();
  });
});
