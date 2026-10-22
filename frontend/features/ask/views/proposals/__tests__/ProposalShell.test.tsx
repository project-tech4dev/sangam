import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/features/ask/lib/rest";
import type { Fact, Proposal, Reader, Work } from "@/features/ask/views/proposals/api";
import { proposal } from "./fixtures";

const call = vi.fn();
vi.mock("@/features/ask/lib/rest", async (original) => ({
  ...(await original<typeof import("@/features/ask/lib/rest")>()),
  call: (...a: unknown[]) => call(...a),
}));
const vault = vi.hoisted(() => ({ list: vi.fn(), upload: vi.fn() }));
vi.mock("@/features/ask/lib/vault", () => ({
  listVault: (...a: unknown[]) => vault.list(...a),
  uploadToVault: (...a: unknown[]) => vault.upload(...a),
}));
// The chat is tested on its own; here it only hands the step its send function.
const chat = vi.hoisted(() => ({ send: vi.fn(), ready: true }));
vi.mock("@/features/ask/views/proposals/TellSangam", () => ({
  TellSangam: ({ onSend, screen: s }: { onSend: (fn: ((t: string) => void) | null) => void; screen: { step: string; part?: string } }) => {
    useEffect(() => onSend(chat.ready ? chat.send : null), [onSend]);
    return <div data-testid="chat">{`${s.step}|${s.part ?? ""}`}</div>;
  },
}));

import { ProposalShell } from "@/features/ask/views/proposals/ProposalShell";

let server: Proposal;
const conflict = (detail: unknown) => new ApiError("conflict", 409, { detail });

function serve(p: Proposal, overrides: Record<string, () => unknown> = {}) {
  server = p;
  call.mockImplementation(async (path: string, method = "GET", payload?: { set?: Record<string, unknown> }) => {
    const key = `${method} ${path}`;
    if (overrides[key]) return overrides[key]();
    if (key === "GET /api/proposals/3") return server;
    if (key === "GET /api/proposals") return [];
    if (key === "PATCH /api/proposals/3/work") {
      const work = { ...server.work, ...(payload?.set?.stage ? { stage: payload.set.stage as number } : {}) };
      return { summary: server.summary, work };
    }
    if (key === "PATCH /api/proposals/3" || key === "POST /api/proposals/3/advance") {
      return { summary: server.summary, work: { ...server.work, stage: key.startsWith("POST") ? server.work.stage + 1 : server.work.stage } };
    }
    throw new Error(`unexpected ${key}`);
  });
}

const workCalls = () => call.mock.calls.filter(([p, m]) => p === "/api/proposals/3/work" && m === "PATCH").map(([, , body]) => body);

function wide(matches: boolean) {
  window.matchMedia = vi.fn(() => ({ matches }) as MediaQueryList);
}

beforeEach(() => {
  wide(true);
  chat.ready = true;
  vault.list.mockResolvedValue([]);
});
afterEach(() => {
  vi.clearAllMocks();
  vi.useRealTimers();
});

const renderShell = (onBack = vi.fn()) => render(<ProposalShell id={3} onBack={onBack} />);

describe("ProposalShell", () => {
  it("shows loading, then a proposal that cannot be opened", async () => {
    call.mockRejectedValue(new Error("404"));
    const onBack = vi.fn();
    renderShell(onBack);
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    expect(await screen.findByText("This proposal could not be opened.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "← All proposals" }));
    expect(onBack).toHaveBeenCalled();
  });

  it("asks each gate in step 1 and saves the answer", async () => {
    serve(proposal({ gates: { csr1: "no" } }, { summary: { ...proposal().summary, to_continue: ["Answer every question"] } }));
    renderShell();
    expect(await screen.findByRole("heading", { name: "Axis proposal" })).toBeInTheDocument();
    expect(screen.getByText(/To Axis · fit 80 \/ 100 · started/)).toBeInTheDocument();
    expect(screen.getByText("Axis cannot fund without this. Get it before you write.")).toBeInTheDocument();
    const gate = screen.getByRole("radiogroup", { name: "Do you have it? CSR-1 registration" });
    expect(within(gate).getByRole("radio", { name: "No" })).toHaveAttribute("aria-checked", "true");
    await userEvent.click(within(gate).getByRole("radio", { name: "Yes, we have it" }));
    expect(workCalls()).toEqual([{ set: { "gates.csr1": "yes" }, rev: {} }]);
    expect(screen.getByRole("button", { name: "Continue to your documents and style →" })).toBeDisabled();
    expect(screen.getByText("To continue: Answer every question.")).toBeInTheDocument();
    expect(screen.getByTestId("chat")).toHaveTextContent("Can you apply?|");
  });

  it("moves to the next step, or says what is still missing", async () => {
    serve(proposal(), {
      "POST /api/proposals/3/advance": () => {
        throw conflict({ missing: ["CSR-1 answer"] });
      },
    });
    renderShell();
    await userEvent.click(await screen.findByRole("button", { name: /Continue to/ }));
    expect(await screen.findByText("To continue: CSR-1 answer.")).toBeInTheDocument();
  });

  it("advances to step 2", async () => {
    serve(proposal());
    renderShell();
    await userEvent.click(await screen.findByRole("button", { name: /Continue to/ }));
    expect(await screen.findByText("Documents Sangam may read")).toBeInTheDocument();
    expect(call).toHaveBeenCalledWith("/api/proposals/3/advance", "POST");
  });

  it("reloads with a notice when a teammate changed it, and shows any other failure", async () => {
    let n = 0;
    serve(proposal(), {
      "PATCH /api/proposals/3/work": () => {
        n += 1;
        throw n === 1 ? conflict({ changed_by: { by: { id: "u2", name: "Ravi" }, at: new Date().toISOString() } }) : new Error("Server down");
      },
    });
    renderShell();
    const gate = await screen.findByRole("radiogroup");
    await userEvent.click(within(gate).getByRole("radio", { name: "No" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Ravi changed this just now. Showing their version.");
    expect(call.mock.calls.filter(([p, m]) => p === "/api/proposals/3" && m === undefined).length).toBe(2);
    await userEvent.click(within(gate).getByRole("radio", { name: "No" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Server down");
  });

  it("renames the proposal, and cancels a rename", async () => {
    serve(proposal());
    renderShell();
    await userEvent.click(await screen.findByRole("button", { name: "Rename" }));
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await userEvent.click(screen.getByRole("button", { name: "Rename" }));
    const name = screen.getByRole("textbox", { name: "Proposal name" });
    await userEvent.clear(name);
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.type(name, "Axis 2027{Enter}");
    expect(call).toHaveBeenCalledWith("/api/proposals/3", "PATCH", { title: "Axis 2027" });
    expect(await screen.findByRole("heading", { name: "Axis 2027" })).toBeInTheDocument();
  });

  it("is read-only for someone who cannot edit", async () => {
    serve(proposal({ gates: { csr1: "yes" } }, { can_edit: false }));
    renderShell();
    expect(await screen.findByText(/You can read this proposal/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Rename" })).toBeNull();
    expect(screen.queryByTestId("chat")).toBeNull();
    expect(screen.queryByRole("button", { name: /Continue to/ })).toBeNull();
    expect(screen.getByRole("radio", { name: "No" })).toBeDisabled();
  });

  it("keeps the chat behind its button on a narrow screen", async () => {
    wide(false);
    serve(proposal());
    renderShell();
    await userEvent.click(await screen.findByRole("button", { name: "Sangam Pitch" }));
    expect(screen.queryByRole("button", { name: "Sangam Pitch" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Close chat" }));
    expect(screen.getByRole("button", { name: "Sangam Pitch" })).toBeInTheDocument();
  });

  it("goes back to an earlier step", async () => {
    serve(proposal({ stage: 2 }));
    renderShell();
    const steps = await screen.findByRole("list", { name: "Steps" });
    expect(within(steps).getByRole("button", { name: /Your documents and style/ })).toBeDisabled();
    await userEvent.click(within(steps).getByRole("button", { name: /Can you apply/ }));
    expect(workCalls()).toContainEqual({ set: { stage: 1 }, rev: {} });
  });

  it("jumps ahead to any step the steps before it allow", async () => {
    serve(proposal({ stage: 2 }, { summary: { ...proposal().summary, furthest: 4 } }), {
      "POST /api/proposals/3/advance?to=4": () => ({ summary: server.summary, work: { ...server.work, stage: 4 } }),
    });
    renderShell();
    const steps = await screen.findByRole("list", { name: "Steps" });
    expect(within(steps).getByRole("button", { name: /Before you send it/ })).toBeDisabled();
    await userEvent.click(within(steps).getByRole("button", { name: /Make a plan/ }));
    expect(call).toHaveBeenCalledWith("/api/proposals/3/advance?to=4", "POST");
    expect(within(steps).getByRole("button", { name: /Make a plan/ })).toHaveAttribute("aria-current", "step");
  });
});

describe("step 2: documents and style", () => {
  const docs = [
    { id: 11, title: "Annual report", doc_type: "annual_report", source_name: null, source_url: null, fetched_at: null, has_file: true },
    { id: 12, title: null, doc_type: null, source_name: null, source_url: null, fetched_at: null, has_file: false },
    { id: 13, title: "Give.do profile", doc_type: "web_page", source_name: null, source_url: "https://give.do/discover/17C4", fetched_at: null, has_file: false },
  ];

  it("ticks files, skips the form and saves the style", async () => {
    vault.list.mockResolvedValue(docs);
    serve(proposal({ stage: 2 }));
    renderShell();
    const report = await screen.findByRole("checkbox", { name: /Annual report/ });
    expect(vault.list).toHaveBeenCalledWith("kabil");
    expect(screen.getByText("annual report")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /Untitled file/ })).toBeDisabled();
    expect(screen.getByText("nothing stored to read; upload the file instead")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /Give.do profile/ })).toBeEnabled();
    expect(screen.getByText("a web page: Sangam saves a copy when it reads it")).toBeInTheDocument();
    await userEvent.click(report);
    expect(workCalls()).toContainEqual({ set: { sources: [11] }, rev: {} });
    await userEvent.click(screen.getByRole("button", { name: "Use Sangam's usual order" }));
    expect(workCalls()).toContainEqual({ set: { skipped_template: true }, rev: {} });
    const style = screen.getByRole("textbox", { name: "Writing style" });
    await userEvent.type(style, " please");
    await userEvent.tab();
    expect(workCalls()).toContainEqual({ set: { style: "Plain and short please" }, rev: {} });
    expect(screen.getByRole("region", { name: "What happens next" })).toBeInTheDocument();
  });

  it("unticks a file and undoes a skipped form", async () => {
    vault.list.mockResolvedValue(docs);
    serve(proposal({ stage: 2, sources: [11], skipped_template: true }));
    renderShell();
    await userEvent.click(await screen.findByRole("checkbox", { name: /Annual report/ }));
    expect(workCalls()).toContainEqual({ set: { sources: [] }, rev: {} });
    await userEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(workCalls()).toContainEqual({ set: { skipped_template: false }, rev: {} });
  });

  it("uploads the funder's form and a source file", async () => {
    vault.upload.mockResolvedValueOnce({ ...docs[0], id: 21, title: "form.pdf" }).mockResolvedValueOnce({ ...docs[0], id: 22, title: "budget.xlsx" });
    serve(proposal({ stage: 2 }));
    const { container } = renderShell();
    await screen.findByText("No files from KABIL yet.");
    const [form, file] = container.querySelectorAll<HTMLInputElement>("input[type=file]");
    await userEvent.upload(form, new File(["x"], "form.pdf"));
    await waitFor(() =>
      expect(workCalls()).toContainEqual({ set: { template: { document_id: 21, url: null, from: "upload", read_at: null }, skipped_template: false }, rev: {} }),
    );
    await userEvent.upload(file, new File(["x"], "budget.xlsx"));
    await waitFor(() => expect(workCalls()).toContainEqual({ set: { sources: [22] }, rev: {} }));
    expect(screen.getByRole("checkbox", { name: /budget.xlsx/ })).toBeInTheDocument();
  });

  it("shows a failed upload and a failed vault load", async () => {
    vault.list.mockRejectedValue(new Error("Vault closed"));
    vault.upload.mockRejectedValue(new Error("Too big"));
    serve(proposal({ stage: 2 }));
    const { container } = renderShell();
    expect(await screen.findByRole("alert")).toHaveTextContent("Vault closed");
    await userEvent.upload(container.querySelector<HTMLInputElement>("input[type=file]")!, new File(["x"], "f.pdf"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Too big");
  });

  it("names a form Sangam already has", async () => {
    serve(proposal({ stage: 2, template: { document_id: 5, url: "https://axis.example/form", from: "sangam", read_at: "2026-09-01T00:00:00Z" } }));
    renderShell();
    expect(await screen.findByText(/Sangam already has it · from/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "open" })).toHaveAttribute("href", "https://axis.example/form");
    expect(screen.getByText(/in the last step you can download them filled into this form\./)).toBeInTheDocument();
  });

  it("offers a funder's form found among the documents as the form, in one change", async () => {
    const form = { status: "failed" as const, at: "x", title: "RF template", error: "RF template looks like the funder's form", looks_like_form: true };
    serve(proposal({ stage: 2, sources: [11, 12], readers: { "12": form } }));
    renderShell();
    const reads = await screen.findByRole("list", { name: "Files read" });
    expect(within(reads).getByText("Not read: RF template looks like the funder's form")).toBeInTheDocument();
    expect(within(reads).queryByRole("button", { name: "Try again" })).toBeNull();
    await userEvent.click(within(reads).getByRole("button", { name: "Use it as the funder's form" }));
    await waitFor(() =>
      expect(workCalls()).toContainEqual({
        set: { template: { document_id: 12, url: null, from: "upload", read_at: null }, skipped_template: false, sources: [11] },
        rev: {},
      }),
    );
  });

  it("leaves the chosen form out of the files to read", async () => {
    vault.list.mockResolvedValue([...docs, { ...docs[0], id: 5, title: "RF template" }]);
    serve(proposal({ stage: 2, template: { document_id: 5, url: null, from: "upload", read_at: null } }));
    renderShell();
    expect(await screen.findByRole("checkbox", { name: /Annual report/ })).toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: /RF template/ })).toBeNull();
  });

  it("names the uploaded form and says when Sangam Pitch reads it", async () => {
    vault.list.mockResolvedValue([...docs, { ...docs[0], id: 5, title: "RF template.pdf" }]);
    serve(proposal({ stage: 2, template: { document_id: 5, url: null, from: "upload", read_at: null } }));
    renderShell();
    expect(await screen.findByText("RF template.pdf")).toBeInTheDocument();
    expect(screen.getByText(/✓ Uploaded/)).toHaveTextContent("Sangam Pitch reads the form then.");
  });

  it("counts the questions once the form is read", async () => {
    const outline = { document_id: 5, read_at: "2026-10-01T00:00:00Z", headings: [{ kind: "prose" }, { kind: "field" }, { kind: "prose" }] };
    serve(proposal({ stage: 2, template: { document_id: 5, url: null, from: "upload", read_at: null, outline } }));
    renderShell();
    expect(await screen.findByText(/✓ Uploaded/)).toHaveTextContent(/Read .*: 2 questions to answer in writing\./);
  });

  it("refuses a funder's form that is not a PDF or Word file, before uploading", async () => {
    serve(proposal({ stage: 2 }));
    const { container } = renderShell();
    await screen.findByText("No files from KABIL yet.");
    const form = container.querySelector<HTMLInputElement>("input[type=file]")!;
    await userEvent.setup({ applyAccept: false }).upload(form, new File(["x"], "form.xlsx"));
    expect(await screen.findByRole("alert")).toHaveTextContent("The funder's form must be a PDF or Word file.");
    expect(vault.upload).not.toHaveBeenCalled();
  });

  it("does not offer a second form once one is chosen", async () => {
    const form = { status: "failed" as const, at: "x", title: "RF template", error: "looks like a form", looks_like_form: true };
    serve(proposal({ stage: 2, sources: [12], readers: { "12": form }, template: { document_id: 5, url: null, from: "upload", read_at: null } }));
    renderShell();
    const reads = await screen.findByRole("list", { name: "Files read" });
    expect(within(reads).queryByRole("button", { name: "Use it as the funder's form" })).toBeNull();
  });

  it("asks Sangam Pitch to write the first draft; secondary research waits for step 3", async () => {
    serve(proposal({ stage: 2 }));
    renderShell();
    await userEvent.click(await screen.findByRole("button", { name: "Write the first draft" }));
    expect(chat.send).toHaveBeenCalledWith("Write the first draft.");
    expect(screen.queryByRole("button", { name: "Search public sources" })).toBeNull();
  });

  it("waits for the chat before the buttons work", async () => {
    chat.ready = false;
    serve(proposal({ stage: 2 }));
    renderShell();
    expect(await screen.findByRole("button", { name: "Write the first draft" })).toBeDisabled();
    expect(screen.getAllByText("Wait for Sangam Pitch to finish its answer.")).toHaveLength(1);
  });

  it("shows each file being read, failed reads and files ticked since", async () => {
    const work: Partial<Work> = {
      stage: 2,
      sources: [11, 12, 13],
      readers: {
        funder: { status: "done", at: "2026-10-01T00:00:00Z", title: "Axis" },
        "11": { status: "done", at: "2026-10-01T00:00:00Z", title: "Annual report" },
        "12": { status: "failed", at: "2026-10-01T00:00:00Z", title: "Scan", error: "scanned image" },
      },
      facts: {
        k1: { subject: "Reach", value: "500", origin: "vault", tier: "green", status: "proposed", document_id: 11 },
        k2: { subject: "Focus", value: "Girls", origin: "web", tier: "amber", status: "proposed" },
      },
    };
    serve(proposal(work));
    renderShell();
    const reads = await screen.findByRole("list", { name: "Files read" });
    expect(within(reads).getByText("What Axis looks for")).toBeInTheDocument();
    expect(within(reads).getAllByText("✓ Read · 1 fact")).toHaveLength(2);
    expect(within(reads).getByText("! Couldn't read: scanned image")).toBeInTheDocument();
    expect(within(reads).getByText("1 file ticked since, not read yet.")).toBeInTheDocument();
    await userEvent.click(within(reads).getByRole("button", { name: "Try again" }));
    expect(chat.send).toHaveBeenCalledWith("Read the files again.");
    await userEvent.click(screen.getByRole("button", { name: "Read the new files" }));
    expect(chat.send).toHaveBeenCalledTimes(2);
  });

  it("follows a teammate's reading by polling the proposal", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    serve(proposal({ stage: 2, sources: [11], readers: { "11": { status: "running", at: "x", title: "Annual report", by: { id: "u2", name: "Ravi" } } } }));
    renderShell();
    expect(await screen.findByText(/Ravi started reading the files/)).toBeInTheDocument();
    const loads = () => call.mock.calls.filter(([p, m]) => p === "/api/proposals/3" && m === undefined).length;
    const before = loads();
    await act(() => vi.advanceTimersByTimeAsync(5000));
    expect(loads()).toBe(before + 1);
  });
});

describe("step 4: make a plan", () => {
  const sections = {
    A1: { text: "Reach is 500 ⟦k1⟧. [Add: dropout rate]", score: 1, rev: 2, missing: ["place"] },
    A2: { text: "Assam", done: true, score: 2 },
    B1: { text: "Budget text" },
  };
  const facts = { k1: { subject: "Reach", value: "500", origin: "vault", tier: "green", status: "proposed", section: "A1", source_name: "Annual report", page: 4 } } as Work["facts"];

  it("opens the first part, scores the tabs and tells Sangam Pitch the part", async () => {
    serve(proposal({ stage: 4, sections, facts }));
    renderShell();
    expect(await screen.findByRole("tab", { name: /Need\s*3\/4/ })).toHaveAttribute("aria-selected", "true");
    expect(screen.queryByRole("tab", { name: /Unused/ })).toBeNull();
    await waitFor(() => expect(screen.getByTestId("chat")).toHaveTextContent("Make a plan|A1"));
    const parts = screen.getByRole("navigation", { name: "Parts" });
    expect(within(parts).getByLabelText("Scored 1 of 2")).toBeInTheDocument();
    expect(within(parts).getByLabelText("Done")).toBeInTheDocument();
    expect(screen.getByText(/Cites 1 source · 1 gap to add · 1 of 3 parts done/)).toBeInTheDocument();
    expect(screen.getByText("Facts for this part (1)")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Write Need again" }));
    expect(chat.send).toHaveBeenCalledWith("Write Need.");
    await userEvent.click(within(parts).getByRole("button", { name: /Place/ }));
    await waitFor(() => expect(screen.getByTestId("chat")).toHaveTextContent("Make a plan|A2"));
    await userEvent.click(screen.getByRole("tab", { name: /Money/ }));
    expect(await screen.findByRole("tab", { name: /Money/ })).toHaveAttribute("aria-selected", "true");
    expect(within(screen.getByRole("navigation", { name: "Parts" })).getByLabelText("Written, not checked")).toBeInTheDocument();
  });

  it("shows a reader the draft or that it is not written", async () => {
    serve(proposal({ stage: 4, sections: { A1: sections.A1 }, facts }, { can_edit: false }));
    renderShell();
    expect(await screen.findByRole("list", { name: "Sources" })).toHaveTextContent("Reach: 500 · Annual report, page 4");
    expect(screen.queryByRole("button", { name: /Write Need/ })).toBeNull();
    await userEvent.click(within(screen.getByRole("navigation", { name: "Parts" })).getByRole("button", { name: /Place/ }));
    expect(screen.getByText("Not written yet.")).toBeInTheDocument();
    expect(within(screen.getByRole("navigation", { name: "Parts" })).getByLabelText("Not written")).toBeInTheDocument();
  });
});

describe("step 5: before you send it", () => {
  it("lists what to fix, rewrites changed parts and confirms every fact", async () => {
    const used = (subject: string) => ({ subject, value: "v", origin: "vault", tier: "green", status: "proposed", used_in: ["A1"] });
    serve(
      proposal(
        { stage: 5, sections: { A1: { text: "x", needs_rewrite: true } }, facts: { k1: used("Reach"), k2: used("Girls") } as Work["facts"] },
        { summary: { ...proposal().summary, fix_first: ["Fill 2 gaps"], worth_checking: [] } },
      ),
    );
    renderShell();
    expect(await screen.findByText("Fill 2 gaps")).toBeInTheDocument();
    expect(screen.getByText("Nothing else to check.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Rewrite that part" }));
    expect(chat.send).toHaveBeenCalledWith("Rewrite Problem: a fact it uses changed.");
    await userEvent.click(screen.getByRole("button", { name: "Confirm all 2" }));
    expect(workCalls()).toContainEqual({ set: { "facts.k1.status": "confirmed", "facts.k2.status": "confirmed" }, rev: {} });
    expect(screen.queryByRole("button", { name: /Continue to/ })).toBeNull();
  });

  it("says when nothing stops it", async () => {
    serve(proposal({ stage: 5 }, { summary: { ...proposal().summary, ready: true, worth_checking: ["Check the budget"] } }));
    renderShell();
    expect(await screen.findByText(/Nothing stops this proposal/)).toBeInTheDocument();
    expect(screen.getByText("Nothing to fix.")).toBeInTheDocument();
    expect(screen.getByText("Check the budget")).toBeInTheDocument();
  });
});

describe("step 3: make a case", () => {
  // The case's own parts: the Summary, written last, and the place.
  const caseSections: Proposal["sections"] = [
    { code: "A1", label: "Summary", question: "Two sentences?", tab: "case", strong: [], weak: "", must_score_2: false, last: true, step: 3 },
    { code: "A2", label: "Context and target area", question: "Where?", tab: "case", strong: [], weak: "", must_score_2: false, last: false, step: 3 },
    { code: "A4", label: "Objectives and results", question: "What changes?", tab: "plan", strong: [], weak: "", must_score_2: false, last: false, step: 4 },
  ];
  const caseTabs = [
    { key: "case", label: "The case", step: 3 },
    { key: "plan", label: "Objectives and plan", step: 4 },
  ];
  const onCase = (work: Partial<Work>, over: Partial<Proposal> = {}) =>
    proposal({ stage: 3, ...work }, { sections: caseSections, tabs: caseTabs, ...over });
  const fact = (subject: string, over: object) => ({ subject, value: "v", origin: "web", tier: "amber", status: "proposed", found_by: "public", ...over });

  it("shows only the case's parts, and the Summary waits for the plan", async () => {
    serve(onCase({ sections: { A2: { text: "Udalguri" } } }));
    renderShell();
    expect(await screen.findByRole("tab", { name: /The case\s*0\/4/ })).toHaveAttribute("aria-selected", "true");
    expect(screen.queryByRole("tab", { name: /Objectives and plan/ })).toBeNull();
    await waitFor(() => expect(screen.getByTestId("chat")).toHaveTextContent("Make a case|A2"));
    expect(screen.queryByText(/Written after your plan/)).toBeNull();
    await userEvent.click(within(screen.getByRole("navigation", { name: "Parts" })).getByRole("button", { name: /Summary/ }));
    expect(screen.getByText(/Written after your plan.*1 part is still/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("chat")).toHaveTextContent("Make a case|A1"));
    expect(screen.queryByRole("button", { name: "Write the Summary" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Write the case again" }));
    expect(chat.send).toHaveBeenCalledWith("Write the case.");
  });

  it("offers to write the Summary once every other part is written", async () => {
    serve(onCase({ sections: { A2: { text: "Udalguri" }, A4: { text: "Fewer dropouts" } } }));
    renderShell();
    await userEvent.click(await screen.findByRole("button", { name: "Write the Summary" }));
    expect(chat.send).toHaveBeenCalledWith("Write the Summary.");
    expect(screen.queryByText(/Written after your plan/)).toBeNull();
  });

  it("shows the researcher's brief on the card, with its tables and links but never raw HTML", async () => {
    const brief = [
      "**A. Problem magnitude**",
      "",
      "| # | Level | Source | Why it matters |",
      "|---|---|---|---|",
      "| 1 | State | [NFHS-5 Assam](https://rchiips.org/nfhs) | 84% of households are rural |",
      "",
      "<script>alert(1)</script>",
      "",
      "[bad](javascript:alert(1))",
    ].join("\n");
    serve(onCase({ readers: { public: { status: "done", at: "2026-10-05T00:00:00Z", title: "Public", brief } } } as Partial<Work>));
    renderShell();
    const card = await screen.findByLabelText("Research brief");
    expect(within(card).getByRole("table")).toBeInTheDocument();
    expect(within(card).getByRole("link", { name: "NFHS-5 Assam" })).toHaveAttribute("href", "https://rchiips.org/nfhs");
    expect(within(card).getByText("bad").closest("a")?.getAttribute("href") ?? "").not.toMatch(/javascript/);
    expect(card.querySelector("script")).toBeNull();
    const facts = screen.getByText(/Facts behind this brief/).closest("details")!;
    expect(facts.open).toBe(false);
    expect(facts.contains(card)).toBe(false);
  });

  it("opens the facts when an older search left no brief", async () => {
    serve(onCase({ readers: { public: { status: "done", at: "2026-10-05T00:00:00Z", title: "Public" } } } as Partial<Work>));
    renderShell();
    expect((await screen.findByText(/Facts behind this brief/)).closest("details")!.open).toBe(true);
    expect(screen.queryByLabelText("Research brief")).toBeNull();
  });

  it("starts fresh or deletes research only after the person confirms", async () => {
    const done = { status: "done", at: "2026-10-05T00:00:00Z", title: "Public", brief: "Old brief" };
    const p = onCase({ readers: { public: done } } as Partial<Work>);
    const cleared = { summary: p.summary, work: { ...p.work, readers: {} } };
    const searching = { summary: p.summary, work: { ...p.work, readers: { public: { status: "running", at: "2026-10-05T00:00:00Z", title: "Public" } } } };
    serve(p, { "DELETE /api/proposals/3/research": () => cleared, "POST /api/proposals/3/research": () => searching });
    renderShell();
    await userEvent.click(await screen.findByRole("button", { name: "Delete research" }));
    const confirm = screen.getByRole("group", { name: "Confirm deleting secondary research" });
    expect(call).not.toHaveBeenCalledWith("/api/proposals/3/research", "DELETE");
    await userEvent.click(within(confirm).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("group", { name: "Confirm deleting secondary research" })).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Start fresh" }));
    await userEvent.click(screen.getByRole("button", { name: "Delete and search" }));
    expect(call).toHaveBeenCalledWith("/api/proposals/3/research", "DELETE");
    expect(call).toHaveBeenCalledWith("/api/proposals/3/research", "POST");
    expect(chat.send).not.toHaveBeenCalled();
    expect(await screen.findByText(/started the search/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Research brief")).toBeNull();
  });

  it("says why research could not be deleted, and does not search", async () => {
    const p = onCase({ readers: { public: { status: "done", at: "2026-10-05T00:00:00Z", title: "Public" } } } as Partial<Work>);
    serve(p, { "DELETE /api/proposals/3/research": () => { throw new Error("A search is running. Try when it's done."); } });
    renderShell();
    await userEvent.click(await screen.findByRole("button", { name: "Start fresh" }));
    await userEvent.click(screen.getByRole("button", { name: "Delete and search" }));
    expect(await screen.findByText("! A search is running. Try when it's done.")).toBeInTheDocument();
    expect(call).not.toHaveBeenCalledWith("/api/proposals/3/research", "POST");
  });

  it("lists each topic's facts with their sources, used or dropped as a whole", async () => {
    const work = {
      readers: {
        public: {
          status: "done",
          at: "2026-10-05T00:00:00Z",
          title: "Public",
          unopened: ["slow.gov.in"],
        },
      },
      facts: {
        k1: fact("Assam dropout", { topic: "problem", value: "15.1%", source_name: "UDISE+", source_url: "https://udiseplus.gov.in/r", as_of: "2023-24" }),
        k2: fact("Udalguri dropout", { topic: "problem", value: "19.8%", source_name: "UDISE+ district" }),
        k3: fact("Stunting", { topic: "problem", value: "30%" }),
        k4: fact("SDG 4", { section: "F1" }),
        k5: fact("Dropped", { status: "rejected", topic: "place" }),
      },
    } as Partial<Work>;
    serve(onCase(work), { "POST /api/proposals/3/research": () => ({ summary: onCase(work).summary, work: onCase(work).work }) });
    renderShell();
    expect(await screen.findByText(/Searched .* · 4 sources/)).toBeInTheDocument();
    expect(screen.getByText("The problem, measured · 3 sources")).toBeInTheDocument();
    const list = screen.getByRole("list", { name: "Sources for The problem, measured" });
    const items = within(list).getAllByRole("listitem").map((li) => li.textContent);
    expect(items).toEqual(["UDISE+ · Assam dropout: 15.1% (2023-24)", "UDISE+ district · Udalguri dropout: 19.8%", "A public source · Stunting: 30%"]);
    expect(within(list).getByRole("link", { name: "UDISE+" })).toHaveAttribute("href", "https://udiseplus.gov.in/r");
    expect(screen.getByText("SDGs · 1 source")).toBeInTheDocument();
    expect(screen.getByText("Why this place · not used")).toBeInTheDocument();
    expect(screen.getByText("What worked elsewhere · none found")).toBeInTheDocument();
    expect(screen.getByText("Couldn't open: slow.gov.in")).toBeInTheDocument();

    const problem = screen.getByText("The problem, measured · 3 sources").closest("details")!;
    await userEvent.click(within(problem).getByRole("button", { name: "Use this" }));
    expect(workCalls()).toContainEqual({ set: { "facts.k1.status": "confirmed", "facts.k2.status": "confirmed", "facts.k3.status": "confirmed" }, rev: {} });
    await userEvent.click(within(problem).getByRole("button", { name: "Don't use" }));
    expect(workCalls()).toContainEqual({ set: { "facts.k1.status": "rejected", "facts.k2.status": "rejected", "facts.k3.status": "rejected" }, rev: {} });
    await userEvent.click(screen.getByRole("button", { name: "Use it after all" }));
    expect(workCalls()).toContainEqual({ set: { "facts.k5.status": "proposed" }, rev: {} });
    await userEvent.click(screen.getByRole("button", { name: "Search again" }));
    expect(call).toHaveBeenCalledWith("/api/proposals/3/research", "POST");
    expect(chat.send).not.toHaveBeenCalled();
  });

  it("marks a topic in use and keeps only Don't use", async () => {
    serve(onCase({ readers: { public: { status: "done", at: "2026-10-05T00:00:00Z", title: "Public" } }, facts: { k1: fact("SDG 4", { topic: "sdg", status: "confirmed" }) } as Work["facts"] }));
    renderShell();
    const sdg = (await screen.findByText("SDGs · 1 source · ✓ using it")).closest("details")!;
    expect(within(sdg).queryByRole("button", { name: "Use this" })).toBeNull();
    expect(within(sdg).getByRole("button", { name: "Don't use" })).toBeInTheDocument();
  });

  it("lists what the person asked for, newest first, and how to ask for more", async () => {
    const ask = { focus: [], sites: [], sections: [], by: { id: "u", name: "Ravi" } };
    serve(
      onCase({
        readers: { public: { status: "done", at: "2026-10-05T00:00:00Z", title: "Public" } },
        research_asks: {
          a1: { ...ask, kind: "chat", ask: "dig into SHG credit", sites: ["nrlm.gov.in"], status: "done", at: "2026-10-05T00:00:00Z", added: 4 },
          a2: { ...ask, kind: "deeper", ask: "", focus: ["MGNREGA days, Assam"], status: "running", at: "2026-10-06T00:00:00Z" },
          a3: { ...ask, kind: "chat", ask: "failed one", status: "failed", at: "2026-10-04T00:00:00Z" },
          a4: { ...ask, kind: "plan", ask: "unit costs", status: "done", at: "2026-10-07T00:00:00Z" },
        },
      }),
    );
    renderShell();
    const asks = within(await screen.findByRole("list", { name: "What you asked for" })).getAllByRole("listitem");
    expect(asks.map((li) => li.textContent)).toEqual([
      expect.stringMatching(/^MGNREGA days, Assamsearching… · /),
      expect.stringMatching(/^dig into SHG creditnrlm\.gov\.in · 4 added · /),
      expect.stringMatching(/^failed onedid not finish · /),
    ]);
    expect(screen.getByText(/Want more\? Tell Sangam Pitch what to dig into/)).toBeInTheDocument();
  });

  it("researches deeper from the case once it is done, with angles the person edits first", async () => {
    const caseDone = { A2: { text: "Udalguri", done: true }, A3: { text: "Low income", done: true } };
    const withProblem = { sections: [...caseSections, { ...caseSections[1], code: "A3", label: "Problem and baseline" }] };
    serve(onCase({ sections: { A2: { text: "Udalguri", done: true } } }, withProblem));
    const { unmount } = renderShell();
    expect(await screen.findByText("To research deeper from your case, mark Problem and baseline done.")).toBeInTheDocument();
    unmount();
    let n = 0;
    serve(onCase({ sections: caseDone }, withProblem), {
      "GET /api/proposals/3/research/angles": () => {
        n += 1;
        if (n === 1) throw new Error("down");
        return { angles: ["MGNREGA days, Udalguri", "SHG credit, Assam"], dropped: ["KABIL members"] };
      },
    });
    renderShell();
    await userEvent.click(await screen.findByRole("button", { name: "Research deeper from your case" }));
    expect(await screen.findByText("Sangam couldn't read your case just now. Try again.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Research deeper from your case" }));
    const chips = await screen.findByRole("list", { name: "What to look into" });
    expect(screen.getByText("Left out, since they name your organisation or a person: KABIL members.")).toBeInTheDocument();
    await userEvent.click(within(chips).getByRole("button", { name: "Remove SHG credit, Assam" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Add something to look into" }), "Women in SHGs, Assam{Enter}");
    expect(within(chips).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["MGNREGA days, Udalguri", "Women in SHGs, Assam"]);
    await userEvent.click(screen.getByRole("button", { name: "Search these" }));
    expect(chat.send).toHaveBeenCalledWith("Research deeper: MGNREGA days, Udalguri; Women in SHGs, Assam.");
    expect(screen.queryByRole("list", { name: "What to look into" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Research deeper from your case" }));
    await userEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("list", { name: "What to look into" })).toBeNull();
  });

  it("lists each researcher while the search runs, and the sources so far", async () => {
    const slices: Reader["slices"] = [
      { label: "Dropout in Kiphire and Tuensang", status: "done" },
      { label: "State schemes on schooling", status: "running" },
      { label: "What worked in the Northeast", status: "failed" },
    ];
    const fact: Fact = { subject: "Dropout", value: "19.8%", origin: "web", tier: "amber", status: "proposed", found_by: "public", section: "A3", topic: "problem" };
    serve(onCase({ readers: { public: { status: "running", at: "x", title: "Public", slices } }, facts: { k1: fact } }));
    renderShell();
    const list = await screen.findByRole("list", { name: "Researchers" });
    expect(within(list).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "Dropout in Kiphire and Tuensang✓ Done",
      "State schemes on schoolingSearching…",
      "What worked in the Northeast! Didn't finish",
    ]);
    expect(screen.getByText(/1 source so far\./)).toBeInTheDocument();
  });

  it("says when secondary research is running or failed", async () => {
    serve(onCase({ readers: { public: { status: "running", at: "x", title: "Public" } } }));
    const { unmount } = renderShell();
    expect(await screen.findByText(/A teammate started the search/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Search/ })).toBeNull();
    unmount();
    serve(onCase({ readers: { public: { status: "failed", at: "x", title: "Public", error: "timeout" } } }));
    renderShell();
    expect(await screen.findByText("! The search did not finish: timeout.")).toBeInTheDocument();
  });
});
