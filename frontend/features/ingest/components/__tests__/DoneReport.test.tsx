import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CoverageConcept, ReviewAnswer } from "../../lib/types";
import { coverage, queueItem, review, status, stubFetch } from "./fakes";

vi.mock("@/lib/api/auth-headers", () => ({ authHeaders: async () => ({}) }));

import { DoneReport } from "../DoneReport";

afterEach(() => vi.unstubAllGlobals());

const concept = (over: Partial<CoverageConcept> = {}): CoverageConcept => ({
  concept: "budget",
  title: "CSR budget",
  cells: [{ year: null, status: "found", detail: "" }],
  fields_filled: 1,
  fields_total: 1,
  held: 0,
  extra_years: [],
  added: 0,
  updated: 0,
  before: 0,
  after: 0,
  ...over,
});
const answer = (i: number): ReviewAnswer => ({
  concept: `c${i}`, topic: `Topic ${i}`, year: null, facts: [], tag: "confirmed", quote: "", source_url: "", source_name: "",
});

const saved = coverage({
  slug: "kabil",
  name: "KABIL",
  stage: "saved",
  entity: { kind: "funder", status: "added", id: 7, name: "KABIL" },
  concepts: [concept({ added: 2, after: 2 }), concept({ concept: "board", title: "Board", before: 1, after: 1 })],
});
const unsaved = coverage({
  slug: "pratham",
  name: "Pratham",
  stage: "unsaved",
  kind: "org",
  concepts: [
    concept({ concept: "reg", title: "Registration", held: 2 }),
    concept({ concept: "fcra", title: "FCRA", cells: [{ year: null, status: "not_stated", detail: "Their site says nothing" }] }),
  ],
});
const since = Date.parse("2026-10-20T00:00:00Z");
const LATE = { timeout: 2000 };

function renderDone(slugs: string[], extra: Partial<Parameters<typeof DoneReport>[0]> = {}) {
  const onStartOver = vi.fn();
  const onCounts = vi.fn();
  render(<DoneReport slugs={slugs} since={since} onStartOver={onStartOver} onCounts={onCounts} fallback={<p>Board</p>} {...extra} />);
  return { onStartOver, onCounts };
}

describe("DoneReport", () => {
  it("shows the fallback until the numbers come, and when none do", async () => {
    stubFetch({ "/coverage": status(404), "/queue": status(500) });
    renderDone(["kabil"]);
    expect(screen.getByText("Board")).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 600));
    expect(screen.getByText("Board")).toBeInTheDocument();
  });

  it("reports a saved organisation's gain, and links its profile", async () => {
    stubFetch({
      "/research/kabil/coverage": saved,
      "/research/kabil/review": review({ answers: Array.from({ length: 11 }, (_, i) => answer(i)) }),
      "/queue": [],
    });
    const { onStartOver, onCounts } = renderDone(["kabil"]);
    expect(await screen.findByRole("heading", { name: "Saved 1 organisation" }, LATE)).toBeInTheDocument();
    expect(screen.getByText(/The saved profile is now 100% complete, up from 50%\. 2 new facts added/)).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Done" })).toBeInTheDocument();
    expect(screen.getByText("+2 facts")).toBeInTheDocument();
    expect(screen.getByLabelText("Profile 50% complete before, 100% after")).toBeInTheDocument();
    await waitFor(() => expect(onCounts).toHaveBeenLastCalledWith({ pending: 0, saved: 1 }));

    await userEvent.click(screen.getByRole("button", { name: /KABIL/ }));
    expect(screen.getByRole("list", { name: "By topic" })).toBeInTheDocument();
    expect(screen.getByText("+2 added")).toBeInTheDocument();
    expect(await screen.findByText("What Sangam found (11)")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Show all 11" }));
    expect(screen.getByText("Topic 10")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Show fewer" }));
    expect(screen.getByRole("link", { name: "Open profile →" })).toHaveAttribute("href", "/registry/funders/7");
    expect(screen.queryByRole("button", { name: "Review & save" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /KABIL.*Hide/ }));

    await userEvent.click(screen.getByRole("button", { name: "Research something else" }));
    expect(onStartOver).toHaveBeenCalledOnce();
  });

  it("asks for a review of unsaved research, with what was missed and held back", async () => {
    stubFetch({
      "/research/pratham/coverage": unsaved,
      "/research/pratham/review": review({ name: "Pratham", missing: [{ concept: "fcra", topic: "FCRA", tag: "not_mentioned", detail: "" }] }),
      "/queue": [queueItem({ created_at: "2026-10-21T00:00:00Z" }), queueItem({ id: 2, raw_name: "Mystery", candidates: [], created_at: "2026-10-21T00:00:00Z" }), queueItem({ id: 3, created_at: "2026-10-01T00:00:00Z" })],
    });
    const { onCounts } = renderDone(["pratham"], { compact: true });
    expect(await screen.findByText(/1 organisation to review\./, {}, LATE)).toBeInTheDocument();
    expect(screen.queryByRole("heading")).not.toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Review" })).toBeInTheDocument();
    expect(screen.getByText("Found answers on 1 of 2 topics")).toBeInTheDocument();
    expect(screen.getByText("Not reviewed")).toBeInTheDocument();
    await waitFor(() => expect(onCounts).toHaveBeenLastCalledWith({ pending: 1, saved: 0 }));

    // Only names queued since the run began.
    expect(screen.getByText("2 names need a person")).toBeInTheDocument();
    expect(screen.getByText("Is “Tata Trust” the same as “Tata Trusts”?")).toBeInTheDocument();
    expect(screen.getByText("Sangam couldn't place “Mystery”.")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /Pratham.*Show/ }));
    expect(screen.getAllByText("Nothing yet")).toHaveLength(2);
    expect(await screen.findByText("Not found, and why")).toBeInTheDocument();
    expect(screen.getByText("Their site says nothing")).toBeInTheDocument();
    expect(screen.getByText("Registration: 2 facts")).toBeInTheDocument();
  });

  it("saves from a row's review, then reloads that row", async () => {
    let stage: "unsaved" | "saved" = "unsaved";
    const fetchMock = stubFetch({
      "/research/pratham/coverage": () =>
        stage === "unsaved" ? unsaved : { ...unsaved, stage: "saved", entity: { kind: "org", status: "added", id: 3, name: "Pratham" } },
      "/research/pratham/review": review({ name: "Pratham" }),
      "/research/pratham/save": () => {
        stage = "saved";
        return { slug: "pratham", entity: { kind: "org", id: 3, name: "Pratham", status: null }, promotion_id: 1, written: 1, held: 0, reasons: [] };
      },
      "/queue": [],
    });
    const { onCounts } = renderDone(["pratham"]);
    await userEvent.click(await screen.findByRole("button", { name: "Review & save" }, LATE));
    await userEvent.click(await screen.findByRole("button", { name: "Save 1 organisation" }));
    expect(await screen.findByRole("heading", { name: "Saved 1 organisation" })).toBeInTheDocument();
    await waitFor(() => expect(onCounts).toHaveBeenLastCalledWith({ pending: 0, saved: 1 }));
    expect(fetchMock.mock.calls.filter(([u]) => String(u).includes("/coverage"))).toHaveLength(2);
  });

  it("marks a declined row Not saved and offers to review it again", async () => {
    stubFetch({ "/research/pratham/coverage": unsaved, "/research/pratham/review": review({ name: "Pratham" }), "/queue": [] });
    const { onCounts } = renderDone(["pratham"]);
    expect(await screen.findByRole("heading", { name: "Review what Scout found" }, LATE)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Pratham.*Show/ }));
    // The open report's own button starts the review too.
    await userEvent.click(screen.getAllByRole("button", { name: "Review & save" }).at(-1)!);
    await userEvent.click(await screen.findByRole("checkbox", { name: "Save Pratham" }));
    await userEvent.click(screen.getByRole("button", { name: "Continue without saving" }));
    expect(await screen.findByRole("heading", { name: "Nothing saved" })).toBeInTheDocument();
    expect(screen.getByText(/Nothing from this run was saved/)).toBeInTheDocument();
    expect(screen.getByText("Not saved")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Review again" })).toBeInTheDocument();
    await waitFor(() => expect(onCounts).toHaveBeenLastCalledWith({ pending: 0, saved: 0 }));
  });

  it("says when the answers could not load, and averages several saved profiles", async () => {
    const second = { ...saved, slug: "tata", name: "Tata", concepts: [concept({ before: 1, after: 1 })] };
    stubFetch({ "/research/kabil/coverage": saved, "/research/tata/coverage": second, "/review": status(500), "/queue": status(500) });
    renderDone(["kabil", "tata"]);
    expect(await screen.findByRole("heading", { name: "Saved 2 organisations" }, LATE)).toBeInTheDocument();
    expect(screen.getByText(/Saved profiles are now 100% complete on average, up from 75%/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /^Tata/ }));
    expect(await screen.findByText("Sangam couldn't load the answers.")).toBeInTheDocument();
    expect(screen.getByText("No change")).toBeInTheDocument();
  });
});
