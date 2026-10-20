import { describe, expect, it } from "vitest";
import { parseBrief } from "@/features/registry/brief/parseBrief";

const BRIEF = `<!-- generated -->
# KABIL Trust

Researched 2026-10-12 · status **partial** · page limit reached
Website: https://kabil.org

A trust working on creches in eastern India.

## What it set out to find
- Programmes and where they run
- Who funds it

## Programmes
- **Bihar · Creches** (FY2024) _reported_
  > Runs 40 creches
  > across two states.
  <sub>Annual report · https://kabil.org/ar.pdf · confidence high</sub>
  - Themes: Early childhood
- **Odisha · Creches** (FY2024) _reported_
  > Runs 40 creches across two states.
  <sub>Annual report · https://kabil.org/ar.pdf · confidence high</sub>
- **Board**
  > Five trustees.

## Notes & Caveats
Free text that is not a finding.

## Empty section

## Looked for, not found
FCRA number.
CSR-1 registration.

## Sources read
- https://kabil.org · website, 3 pages
- https://kabil.org/ar.pdf · document

---
Closing note the page writes itself.
## Ignored
`;

describe("parseBrief", () => {
  const brief = parseBrief(BRIEF);

  it("reads the header: name, status line, website and summary", () => {
    expect(brief.name).toBe("KABIL Trust");
    expect(brief.researched).toBe("2026-10-12");
    expect(brief.status).toBe("partial");
    expect(brief.stopped).toBe("page limit reached");
    expect(brief.website).toBe("https://kabil.org");
    expect(brief.summary).toBe("A trust working on creches in eastern India.");
  });

  it("collects goals, what was not found and the source urls", () => {
    expect(brief.goals).toEqual(["Programmes and where they run", "Who funds it"]);
    expect(brief.notFound).toBe("FCRA number. CSR-1 registration.");
    expect(brief.sources).toEqual(["https://kabil.org", "https://kabil.org/ar.pdf"]);
  });

  it("folds one quote shared by two rows into one finding", () => {
    const programmes = brief.sections.find((s) => s.id === "programmes")!;
    expect(programmes.title).toBe("Programmes");
    expect(programmes.findings).toHaveLength(2);
    const [creches, board] = programmes.findings;
    expect(creches.headlines).toEqual(["Bihar · Odisha — Creches"]);
    expect(creches.year).toBe("FY2024");
    expect(creches.basis).toBe("reported");
    expect(creches.evidence).toBe("Runs 40 creches across two states.");
    expect(creches.source).toEqual({ name: "Annual report", url: "https://kabil.org/ar.pdf", confidence: "high" });
    expect(creches.details).toEqual([{ label: "Themes", value: "Early childhood" }]);
    expect(board).toMatchObject({ headlines: ["Board"], evidence: "Five trustees." });
  });

  it("keeps free text, drops empty sections and stops at the closing rule", () => {
    expect(brief.sections.map((s) => s.id)).toEqual(["programmes", "notes-caveats"]);
    expect(brief.sections[1].text).toBe("Free text that is not a finding.");
    expect(brief.sections[1].findings).toEqual([]);
  });

  it("keeps rows with different tails as separate headlines under one quote", () => {
    const md = `# X\n\n## Work\n- **Bihar · Creches**\n  > Same.\n- **Odisha · Schools**\n  > Same.\n`;
    expect(parseBrief(md).sections[0].findings[0].headlines).toEqual(["Bihar · Creches", "Odisha · Schools"]);
  });

  it("names an unnamed source and survives an empty document", () => {
    const md = `# X\n## Work\n- **Y**\n  > Z\n  <sub>https://y.org · confidence low</sub>\n`;
    expect(parseBrief(md).sections[0].findings[0].source).toEqual({ name: "source", url: "https://y.org", confidence: "low" });
    expect(parseBrief("")).toEqual({ name: "", summary: "", goals: [], sections: [], sources: [] });
  });
});
