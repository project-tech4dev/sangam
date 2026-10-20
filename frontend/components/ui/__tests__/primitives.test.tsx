import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Breadcrumbs, EntityMark, Hero, initialsOf, PillTabs, ProgressBar, StatRail, StatusChip, Tag } from "@/components/ui";
import { SectionIndex } from "@/components/ui/SectionIndex";

describe("initialsOf", () => {
  it("takes two words' initials, skipping filler and brackets", () => {
    expect(initialsOf("The Tata Trusts")).toBe("TT");
    expect(initialsOf("Bank of Baroda")).toBe("BB");
    expect(initialsOf("(KABIL)")).toBe("KA");
    expect(initialsOf("kabil")).toBe("KA");
  });
});

describe("display primitives", () => {
  it("Breadcrumbs links all but the plain last item", () => {
    render(<Breadcrumbs items={[{ label: "Registry", href: "/registry" }, { label: "KABIL" }]} />);
    expect(screen.getByRole("link", { name: "Registry" })).toHaveAttribute("href", "/registry");
    expect(screen.queryByRole("link", { name: "KABIL" })).toBeNull();
    expect(screen.getByText("/")).toBeInTheDocument();
  });

  it("Tag and StatusChip show their text and tone", () => {
    render(<><Tag tone="accent">Health</Tag><StatusChip status="verified" /><StatusChip status={"bogus" as "full"} /></>);
    expect(screen.getByText("Health")).toHaveClass("tag-accent");
    expect(screen.getByText("Verified")).toHaveClass("tag-accent-2");
    expect(screen.getByText("Pending review")).toBeInTheDocument();
  });

  it("EntityMark shows initials and ProgressBar clamps", () => {
    render(<><EntityMark name="Pratham Education" /><ProgressBar pct={140} /></>);
    expect(screen.getByText("PE")).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "100");
  });

  it("StatRail shows an em dash and says when a value is not entered", () => {
    render(<StatRail stats={[{ value: 12, label: "Funders" }, { value: null, label: "Grants" }]} />);
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.getByText("Grants — not yet entered")).toBeInTheDocument();
  });

  it("Hero shows only the parts it is given", () => {
    const { rerender } = render(<Hero name="Tata Trusts" kicker="Funder" blurb="Grants across India" cta={<button>Match</button>} />);
    expect(screen.getByRole("heading", { level: 1, name: "Tata Trusts" })).toBeInTheDocument();
    expect(screen.getByText("Funder")).toBeInTheDocument();
    expect(screen.getByText("Grants across India")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Match" })).toBeInTheDocument();
    rerender(<Hero name="Tata Trusts" />);
    expect(screen.queryByText("Funder")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("PillTabs", () => {
  it("selects the active tab and reports a pick, in both looks", async () => {
    const onPick = vi.fn();
    const tabs = [{ id: "a", label: "Mandate" }, { id: "b", label: "Giving" }];
    const { rerender } = render(<PillTabs tabs={tabs} active="a" onPick={onPick} label="Profile" />);
    expect(screen.getByRole("tablist", { name: "Profile" })).toHaveClass("pill-tabs");
    expect(screen.getByRole("tab", { name: "Mandate" })).toHaveAttribute("aria-selected", "true");
    await userEvent.click(screen.getByRole("tab", { name: "Giving" }));
    expect(onPick).toHaveBeenCalledWith("b");
    rerender(<PillTabs tabs={tabs} active="b" onPick={onPick} variant="board" />);
    expect(screen.getByRole("tablist")).toHaveClass("profile-tablist");
    expect(screen.getByRole("tab", { name: "Giving" })).toHaveAttribute("aria-selected", "true");
  });
});

describe("SectionIndex", () => {
  const sections = [{ id: "one", label: "One" }, { id: "two", label: "Two", sub: true }];

  it("marks the first section current and jumps to a clicked one", async () => {
    const scrollTo = vi.fn();
    vi.stubGlobal("scrollTo", scrollTo);
    render(<><div id="one" /><div id="two" /><SectionIndex sections={sections} title="In this article" /></>);
    // Push "two" below the fold, then rescroll, so only "one" is in view.
    document.getElementById("two")!.getBoundingClientRect = () => ({ top: 900 }) as DOMRect;
    act(() => window.dispatchEvent(new Event("scroll")));
    expect(screen.getByRole("navigation", { name: "In this article" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "One" })).toHaveAttribute("aria-current", "true");
    await userEvent.click(screen.getByRole("link", { name: "Two" }));
    expect(scrollTo).toHaveBeenCalledWith({ top: 900 - 96, behavior: "smooth" });
    expect(window.location.hash).toBe("#two");
    expect(screen.getByRole("link", { name: "Two" })).toHaveAttribute("aria-current", "true");
    vi.unstubAllGlobals();
  });

  it("follows the scroll to the section in view", () => {
    render(<><div id="one" /><div id="two" /><SectionIndex sections={sections} /></>);
    // jsdom lays nothing out, so every section sits at top 0, inside the offset: the last one wins.
    expect(screen.getByRole("navigation", { name: "Sections" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Two" })).toHaveAttribute("aria-current", "true");
  });

  it("lets the browser follow a link whose section is missing", async () => {
    render(<SectionIndex sections={[{ id: "gone", label: "Gone" }]} />);
    const link = screen.getByRole("link", { name: "Gone" });
    expect(link).toHaveAttribute("href", "#gone");
    await userEvent.click(link);
    expect(window.location.hash).toBe("#gone");
  });
});
