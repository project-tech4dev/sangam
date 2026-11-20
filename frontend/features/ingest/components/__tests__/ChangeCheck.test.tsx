import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CheckRunDetail } from "../../lib/changeCheck";
import { status, stubFetch } from "./fakes";

vi.mock("@/lib/api/auth-headers", () => ({ authHeaders: async () => ({}) }));

import { ChangeCheck, SourceResult, stepOf } from "../ChangeCheck";

const BASELINE = {
  slug: "apf",
  unrecorded: 0,
  sources: [{ url: "https://a.org/report.pdf", kind: "document", snapshot_id: 1, read_on: "2026-11-19", archived: true, facts: 79 }],
};

const detail = (over: Partial<CheckRunDetail> = {}): CheckRunDetail => ({
  run_id: "r1",
  slug: "apf",
  depth: "free",
  decision: "refresh",
  started_at: "2026-11-19T08:00:00Z",
  finished_at: "2026-11-19T08:01:00Z",
  error: null,
  refresh_row_id: null,
  refresh_summary: null,
  requested_by: "dev@sangam.local",
  sources: 1,
  checks: [
    {
      url: "https://a.org/report.pdf",
      status: "changed",
      detail: "facts: 0 intact, 1 broken, 0 unanchored",
      findings_intact: 0,
      findings_broken: 1,
      findings_unanchored: 0,
      judge: null,
      removed_text: ["We fund 400 schools."],
      added_text: ["We fund 500 schools."],
      evidence: [{ verdict: "broken", sentence: "We fund 400 schools." }],
      baseline_snapshot_id: 1,
      new_snapshot_id: 10,
      baseline_seen_at: "2026-11-19T07:44:00Z",
    },
  ],
  ...over,
});

afterEach(() => vi.unstubAllGlobals());

describe("ChangeCheck", () => {
  it("shows what Sangam holds and runs a free check without asking about cost", async () => {
    const confirm = vi.fn(() => true);
    vi.stubGlobal("confirm", confirm);
    let ran = false;
    const reply = (body: unknown) => ({ ok: true, status: 200, json: async () => body }) as Response;
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      if (url.includes("/baseline")) return reply(BASELINE);
      if (init?.method === "POST") {
        ran = true;
        expect(JSON.parse(String(init.body))).toEqual({ depth: "free", refresh: false });
        return reply(detail());
      }
      return reply(ran ? [detail()] : []);
    }));
    render(<ChangeCheck slug="apf" name="Azim Premji Foundation" />);
    expect(await screen.findByText(/79 facts/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Check for changes" }));
    expect(await screen.findByText("A change found")).toBeInTheDocument();
    expect(confirm).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: /Update what changed/ })).toBeInTheDocument();
  });

  it("asks before an update that costs money, and does nothing on no", async () => {
    vi.stubGlobal("confirm", vi.fn(() => false));
    const fetchMock = stubFetch({ "/baseline": BASELINE, "/research/apf/checks": [detail()], "/checks/r1": detail() });
    render(<ChangeCheck slug="apf" name="APF" />);
    await userEvent.click(await screen.findByRole("button", { name: /Update what changed/ }));
    const posts = fetchMock.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === "POST");
    expect(posts).toHaveLength(0);
  });

  it("says there is nothing to compare when no research records its versions", async () => {
    stubFetch({ "/baseline": { ...BASELINE, sources: [] }, "/research/apf/checks": [] });
    render(<ChangeCheck slug="apf" name="APF" />);
    expect(await screen.findByText(/nothing to compare/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Check for changes" })).toBeDisabled();
  });

  it("shows the backend's reason when it refuses", async () => {
    stubFetch({ "/baseline": status(403, { detail: "Staff only" }), "/research/apf/checks": [] });
    render(<ChangeCheck slug="apf" name="APF" />);
    await waitFor(() => expect(screen.getByText("Staff only")).toBeInTheDocument());
  });
});

describe("SourceResult", () => {
  it("opens to its steps, the diff and each fact's verdict", async () => {
    render(<SourceResult check={detail().checks[0]} />);
    await userEvent.click(screen.getByText("a.org/report.pdf"));
    expect(screen.getByRole("list", { name: "How this source was checked" }).children).toHaveLength(5);
    expect(screen.getByText(/− We fund 400 schools/)).toBeInTheDocument();
    expect(screen.getByText(/\+ We fund 500 schools/)).toBeInTheDocument();
    expect(screen.getByText("✗ Gone or changed")).toBeInTheDocument();
  });
});

describe("stepOf", () => {
  it("follows the run", () => {
    expect(stepOf(null)).toBe(0);
    expect(stepOf(detail({ finished_at: null }))).toBe(1);
    expect(stepOf(detail())).toBe(2);
    expect(stepOf(detail({ refresh_row_id: 91 }))).toBe(3);
    expect(stepOf(detail({ decision: "nothing to do" }))).toBe(4);
  });
});
