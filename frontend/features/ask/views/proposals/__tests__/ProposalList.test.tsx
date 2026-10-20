import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { ProposalItem } from "@/features/ask/views/proposals/api";
import { ProposalList } from "@/features/ask/views/proposals/ProposalList";

const now = Date.now();
const bucket = (name: RegExp) => within(screen.getByRole("group", { name: "Show" })).getByRole("button", { name });
const iso = (daysAgo: number) => new Date(now - daysAgo * 86_400_000).toISOString();

const item = (id: number, title: string, over: Partial<ProposalItem> = {}): ProposalItem => ({
  id,
  title,
  org: { id: 1, slug: "kabil", name: "KABIL" },
  funder: { id: 10, slug: "axis", name: "Axis" },
  fit_score: 80,
  created_at: iso(5),
  updated_at: iso(1),
  summary: { stage: 2, gates_answered: 1, gates_total: 2, done: 1, total: 6, fix_first: [], worth_checking: [], ready: false },
  can_edit: true,
  ...over,
});

const rows = [
  item(1, "Axis libraries"),
  item(2, "Tata health", {
    funder: { id: 20, slug: "tata", name: "Tata" },
    org: { id: 2, slug: "seva", name: "Seva" },
    created_at: iso(60),
    fit_score: null,
    summary: { ...item(0, "").summary, stage: 4, ready: true },
  }),
];

describe("ProposalList", () => {
  it("lists each proposal with its step and parts, and opens one", async () => {
    const onOpen = vi.fn();
    render(<ProposalList rows={rows} initialFunder={null} onOpen={onOpen} onFunderMatch={vi.fn()} />);
    expect(screen.getByText(/To Axis · KABIL · Step 2 of 4, your documents and style · 1 of 6 parts done · fit 80 \/ 100/)).toBeInTheDocument();
    expect(screen.getByText("2 of 2 proposals · newest first")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Tata health/ }));
    expect(onOpen).toHaveBeenCalledWith(2);
  });

  it("narrows by bucket, funder, organisation, start date and search", async () => {
    render(<ProposalList rows={rows} initialFunder={null} onOpen={vi.fn()} onFunderMatch={vi.fn()} />);
    await userEvent.click(bucket(/Ready/));
    expect(screen.queryByRole("button", { name: /Axis libraries/ })).toBeNull();
    await userEvent.click(bucket(/In progress/));
    expect(screen.queryByRole("button", { name: /Tata health/ })).toBeNull();
    await userEvent.click(bucket(/All proposals/));
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Organisation" }), "seva");
    expect(screen.getByText("1 of 2 proposals · newest first")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Organisation" }), "all");
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Started" }), "30");
    expect(screen.queryByRole("button", { name: /Tata health/ })).toBeNull();
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Started" }), "any");
    await userEvent.type(screen.getByRole("searchbox"), "nope");
    expect(screen.getByText("No proposals match these filters.")).toBeInTheDocument();
  });

  it("opens filtered to the funder Funder Match came from", () => {
    render(<ProposalList rows={rows} initialFunder={20} onOpen={vi.fn()} onFunderMatch={vi.fn()} />);
    expect(screen.getByRole("combobox", { name: "Funder" })).toHaveValue("20");
    expect(screen.queryByRole("button", { name: /Axis libraries/ })).toBeNull();
  });

  it("points to Funder Match when there are none", async () => {
    const onFunderMatch = vi.fn();
    render(<ProposalList rows={[]} initialFunder={null} onOpen={vi.fn()} onFunderMatch={onFunderMatch} />);
    expect(screen.getByText("No proposals yet")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Open Funder Match →" }));
    expect(onFunderMatch).toHaveBeenCalled();
  });
});
