import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/features/ask/lib/rest";
import type { Fact, Proposal, Saved, Work } from "@/features/ask/views/proposals/api";
import { proposal } from "./fixtures";

const call = vi.fn();
vi.mock("@/features/ask/lib/rest", async (original) => ({
  ...(await original<typeof import("@/features/ask/lib/rest")>()),
  call: (...a: unknown[]) => call(...a),
}));

import { FactList, source } from "@/features/ask/views/proposals/FactList";
import { FinishCard } from "@/features/ask/views/proposals/FinishCard";
import { numbering, PartEditor, WriteCard } from "@/features/ask/views/proposals/WriteCard";

const fact = (over: Partial<Fact> = {}): Fact => ({ subject: "Reach", value: "500", origin: "vault", tier: "green", status: "proposed", section: "A1", ...over });

afterEach(() => {
  vi.clearAllMocks();
  vi.useRealTimers();
});

describe("FactList", () => {
  const facts: Record<string, Fact> = {
    k1: fact({ source_name: "Annual report", page: 3, as_of: "2025" }),
    k2: fact({ subject: "Said", origin: "you_said", tier: "said", said_by: { id: "u", name: "Asha" } }),
    k3: fact({ subject: "Confirmed", status: "confirmed", origin: "registry", marker: "[org:1]" }),
    k4: fact({ subject: "Gone", status: "rejected" }),
    k5: fact({ subject: "Public", origin: "web", found_by: "public", marker: "[activity:2]" }),
    k6: fact({ subject: "Derived", origin: "derived" }),
  };

  it("shows each fact's standing and source in words, and lets an editor decide", async () => {
    const save = vi.fn(async () => {});
    render(<FactList proposal={proposal({ facts })} part="A1" save={save} />);
    const list = screen.getByRole("list", { name: "Facts for this part" });
    expect(within(list).getByText("✓ From your document")).toBeInTheDocument();
    expect(within(list).getByText(/Annual report, page 3/)).toBeInTheDocument();
    expect(within(list).getByText("Asha said this")).toBeInTheDocument();
    expect(within(list).getByText("✓ Confirmed")).toBeInTheDocument();
    expect(within(list).getByText(/Sangam's record of your organisation/)).toBeInTheDocument();
    expect(within(list).getByText("! From secondary research, not checked")).toBeInTheDocument();
    expect(within(list).getByText("! Worked out by Sangam, not checked")).toBeInTheDocument();
    expect(within(list).getByText("1 fact set aside or replaced.")).toBeInTheDocument();
    const first = within(list).getByText("Reach").closest("li")!;
    await userEvent.click(within(first).getByRole("button", { name: "Yes, it's right" }));
    expect(save).toHaveBeenCalledWith({ "facts.k1.status": "confirmed" });
    await userEvent.click(within(first).getByRole("button", { name: "Don't use it" }));
    expect(save).toHaveBeenCalledWith({ "facts.k1.status": "rejected" });
  });

  it("corrects a value", async () => {
    const save = vi.fn(async () => {});
    render(<FactList proposal={proposal({ facts: { k1: fact() } })} part="A1" save={save} />);
    await userEvent.click(screen.getByRole("button", { name: "No, change it" }));
    const box = screen.getByRole("textbox", { name: "The right value for Reach" });
    await userEvent.clear(box);
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await userEvent.click(screen.getByRole("button", { name: "No, change it" }));
    await userEvent.type(screen.getByRole("textbox"), "0{Enter}");
    expect(save).toHaveBeenCalledWith({ "facts.k1.correct": "5000" });
    await waitFor(() => expect(screen.queryByRole("textbox")).toBeNull());
  });

  it("names the parts a used fact appears in, and says when none is used", () => {
    const p = proposal({ facts: { k1: fact({ used_in: ["A1", "Z9"] }) } });
    const { unmount } = render(<FactList proposal={p} part="used" save={vi.fn()} />);
    expect(screen.getByText(/used in Problem, Z9/)).toBeInTheDocument();
    unmount();
    render(<FactList proposal={proposal()} part="used" save={vi.fn()} />);
    expect(screen.getByText(/No part cites a fact yet/)).toBeInTheDocument();
  });

  it("offers no buttons to a reader, and says when a part has no facts", () => {
    const { unmount } = render(<FactList proposal={proposal({ facts: { k1: fact() } }, { can_edit: false })} part="A1" save={vi.fn()} />);
    expect(screen.queryByRole("button")).toBeNull();
    unmount();
    render(<FactList proposal={proposal()} part="A1" save={vi.fn()} />);
    expect(screen.getByText(/No facts for this part yet/)).toBeInTheDocument();
  });

  it("names a source by its marker kind", () => {
    expect(source(fact({ marker: "[score:1]" }))).toBe("Funder Match");
    expect(source(fact())).toBeNull();
  });
});

describe("WriteCard", () => {
  it("numbers sources by first use and marks gaps", () => {
    const facts = { k7: fact({ subject: "A" }), k2: fact({ subject: "B", origin: "you_said", said_by: undefined }) };
    const text = "First ⟦k7⟧⟦k2⟧ then ⟦k9⟧.\n\nSecond [Add: a figure] and ⟦k2⟧.";
    const p = proposal({ sections: { A1: { text, score: 2, needs_rewrite: true } }, facts });
    render(<WriteCard proposal={p} code="A1" />);
    expect(screen.getByText("Strong")).toBeInTheDocument();
    expect(screen.getByText("A fact it uses changed: needs rewriting")).toBeInTheDocument();
    expect(screen.getByText("1 gap to fill")).toBeInTheDocument();
    expect(screen.getByText("1,2")).toBeInTheDocument();
    expect(screen.getByText("Add: a figure")).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Sources" })).toHaveTextContent("A: 500B: 500 · Your team said this");
  });

  it("renders nothing for an empty part", () => {
    const { container } = render(<WriteCard proposal={proposal()} code="A1" />);
    expect(container).toBeEmptyDOMElement();
  });

  it("numbers cited facts first, then the part's other live facts", () => {
    const facts = { k3: fact(), k10: fact(), k1: fact(), k4: fact({ status: "rejected" }), k5: fact({ section: "B1" }) };
    expect(numbering("x ⟦k10⟧", facts, "A1")).toEqual(["k10", "k1", "k3"]);
  });
});

describe("PartEditor", () => {
  const section = proposal().sections[0];
  const saved = (work: Partial<Work>): Saved => ({ summary: proposal().summary, work: { ...proposal().work, ...work } });

  function editor(p: Proposal, over: { send?: ((t: string) => void) | null; onSaved?: (s: Saved) => void; onNext?: () => void } = {}) {
    const props = { proposal: p, section, next: p.sections[1], onNext: over.onNext ?? vi.fn(), onSaved: over.onSaved ?? vi.fn(), send: over.send ?? null };
    return { ...render(<PartEditor {...props} />), props };
  }

  it("asks Sangam Pitch to write an empty part, and moves to the next", async () => {
    const send = vi.fn();
    const onNext = vi.fn();
    editor(proposal(), { send, onNext });
    expect(screen.getByText("Must score 2")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Write" }));
    expect(send).toHaveBeenCalledWith("Write Problem.");
    await userEvent.click(screen.getByRole("button", { name: "Place →" }));
    expect(onNext).toHaveBeenCalled();
  });

  it("shows typed numbers for sources and saves them back as facts on Done", async () => {
    const facts = { k4: fact({ subject: "Reach" }), k7: fact({ subject: "Girls" }) };
    const p = proposal({ sections: { A1: { text: "Reach ⟦k4⟧.", rev: 3, score: 1, missing: ["place"], untraced: ["90%"] } }, facts });
    const onSaved = vi.fn();
    call.mockImplementation(async (path: string) => (path === "/api/proposals" ? [] : saved({ sections: { A1: { text: "Reach ⟦k4⟧⟦k7⟧.", rev: 4, done: true } }, facts })));
    editor(p, { onSaved });
    const box = screen.getByRole("textbox", { name: "Problem" });
    expect(box).toHaveValue("Reach [1].");
    expect(screen.getByText(/No source yet: “90%”/)).toBeInTheDocument();
    expect(screen.getByText(/One element missing · must be 2/)).toBeInTheDocument();
    expect(within(screen.getByRole("list", { name: "What a strong answer covers" })).getByText("✓ data")).toBeInTheDocument();
    await userEvent.clear(box);
    await userEvent.type(box, "Reach [[1,2].");
    await userEvent.click(screen.getByRole("button", { name: "Done" }));
    // Leaving the box saves the text; Done, pressed meanwhile, follows at the new revision.
    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(2));
    const sent = call.mock.calls.filter(([path]) => path === "/api/proposals/3/work").map(([, , body]) => body);
    expect(sent).toEqual([
      { set: { "sections.A1.text": "Reach ⟦k4⟧⟦k7⟧." }, rev: { A1: 3 } },
      { set: { "sections.A1.done": true }, rev: { A1: 4 } },
    ]);
    expect(box).toHaveValue("Reach [1,2].");
  });

  it("saves after a pause in typing", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    call.mockImplementation(async (path: string) => (path === "/api/proposals" ? [] : saved({ sections: { A1: { text: "Hello", rev: 1 } } })));
    editor(proposal());
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await user.type(screen.getByRole("textbox", { name: "Problem" }), "Hello");
    expect(screen.getByText("Press Done to check it against these.")).toBeInTheDocument();
    await act(() => vi.advanceTimersByTimeAsync(1600));
    expect(call).toHaveBeenCalledWith("/api/proposals/3/work", "PATCH", { set: { "sections.A1.text": "Hello" }, rev: { A1: 0 } });
  });

  it("says a save failed", async () => {
    call.mockRejectedValue(new Error("down"));
    editor(proposal());
    await userEvent.type(screen.getByRole("textbox", { name: "Problem" }), "Hi");
    await userEvent.tab();
    expect(await screen.findByText("Not saved. Keep typing to try again.")).toBeInTheDocument();
  });

  it("takes a teammate's text after a conflict and keeps the person's below", async () => {
    const detail = { section: "A1", current: { text: "Their text", rev: 5 }, changed_by: { by: { id: "u2", name: "Ravi" }, at: "x" } };
    call.mockRejectedValue(new ApiError("conflict", 409, { detail }));
    editor(proposal());
    await userEvent.type(screen.getByRole("textbox", { name: "Problem" }), "Mine");
    await userEvent.tab();
    expect(await screen.findByText(/Ravi changed this part a moment ago/)).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Problem" })).toHaveValue("Their text");
    expect(screen.getByRole("textbox", { name: "Your text" })).toHaveValue("Mine");
    await userEvent.click(screen.getByRole("button", { name: "Done with it" }));
    expect(screen.queryByRole("textbox", { name: "Your text" })).toBeNull();
  });

  it("calls a conflict from the person's own chat Sangam Pitch's", async () => {
    const detail = { section: "A1", current: { text: "Pitch text", rev: 5 }, changed_by: { by: { id: "u1", name: "Me" }, at: "x" } };
    call.mockRejectedValue(new ApiError("conflict", 409, { detail }));
    editor(proposal());
    await userEvent.type(screen.getByRole("textbox", { name: "Problem" }), "Mine");
    await userEvent.tab();
    expect(await screen.findByText(/Sangam Pitch changed this part/)).toBeInTheDocument();
  });

  it("follows a newer revision from the server when nothing was typed", () => {
    const { rerender, props } = editor(proposal({ sections: { A1: { text: "Old", rev: 1 } } }));
    rerender(<PartEditor {...props} proposal={proposal({ sections: { A1: { text: "New from Pitch", rev: 2 } } })} />);
    expect(screen.getByRole("textbox", { name: "Problem" })).toHaveValue("New from Pitch");
  });

  it("reopens a done part, and grades a weak one", async () => {
    call.mockImplementation(async (path: string) => (path === "/api/proposals" ? [] : saved({ sections: { A1: { text: "x", rev: 2 } } })));
    editor(proposal({ sections: { A1: { text: "x", rev: 1, done: true, score: 0, missing: ["data", "place"] } } }));
    expect(screen.getByText("Reads as weak: vague · must be 2")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Done · reopen" }));
    expect(call).toHaveBeenCalledWith("/api/proposals/3/work", "PATCH", { set: { "sections.A1.done": false }, rev: { A1: 1 } });
  });

  it("marks a part to write last and counts its gaps", () => {
    const last = proposal().sections[2];
    render(
      <PartEditor
        proposal={proposal({ sections: { B1: { text: "[Add: total] and [Add: split]", score: 2, missing: [] } } })}
        section={last}
        next={null}
        onNext={vi.fn()}
        onSaved={vi.fn()}
        send={null}
      />,
    );
    expect(screen.getByText(/Write this last/)).toBeInTheDocument();
    expect(screen.getByText("2 to add")).toBeInTheDocument();
    expect(screen.getByText("Strong")).toBeInTheDocument();
  });
});

describe("FinishCard", () => {
  const written = { A1: { text: "x", rev: 2 }, A2: { text: "y", rev: 1 } };
  const version = { n: 1, title: "Axis proposal v1", document_id: 77, at: "2026-10-10T00:00:00Z", by: { id: "u", name: "Asha" } };
  const assign = vi.fn();

  function stubLocation() {
    vi.stubGlobal("location", { ...window.location, assign });
  }
  afterEach(() => vi.unstubAllGlobals());

  it("says nothing is written yet", () => {
    render(<FinishCard proposal={proposal()} onSaved={vi.fn()} />);
    expect(screen.getByText("Nothing is written yet.")).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("saves a Word file and downloads it", async () => {
    stubLocation();
    const onSaved = vi.fn();
    call.mockImplementation(async (path: string) => {
      if (path === "/api/proposals/3/versions") return { summary: proposal().summary, work: { ...proposal().work, versions: [version] } };
      if (path === "/api/documents/77/file") return { url: "https://files.example/v1.docx" };
      return [];
    });
    render(<FinishCard proposal={proposal({ sections: written })} onSaved={onSaved} />);
    expect(screen.getByText("No version saved yet. Each download is kept in your Doc Vault as the next version.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Download as a Word file" }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith("https://files.example/v1.docx"));
    expect(onSaved).toHaveBeenCalled();
  });

  it("lists saved versions, newest first, and opens one", async () => {
    stubLocation();
    call.mockRejectedValueOnce(new Error("gone")).mockResolvedValueOnce({ url: "https://files.example/v2.docx" });
    const versions = [version, { ...version, n: 2, title: "Axis proposal v2", document_id: 78 }];
    render(<FinishCard proposal={proposal({ sections: written, versions }, { can_edit: false })} onSaved={vi.fn()} />);
    const list = screen.getByRole("list", { name: "Saved versions" });
    expect(within(list).getAllByRole("listitem")[0]).toHaveTextContent("Axis proposal v2");
    await userEvent.click(within(list).getAllByRole("button", { name: "Download" })[0]);
    expect(await screen.findByRole("alert")).toHaveTextContent("That file could not be opened. Try again.");
    await userEvent.click(within(list).getAllByRole("button", { name: "Download" })[0]);
    await waitFor(() => expect(assign).toHaveBeenCalledWith("https://files.example/v2.docx"));
    expect(screen.queryByRole("button", { name: /Smooth/ })).toBeNull();
  });

  it("smooths the language, and shows what a refused smoothing changed", async () => {
    const onSaved = vi.fn();
    call
      .mockRejectedValueOnce(new ApiError("refused", 409, { detail: { differences: ["500 became 50"] } }))
      .mockRejectedValueOnce(new Error("Model busy"))
      .mockResolvedValueOnce({ summary: proposal().summary, work: proposal().work });
    render(<FinishCard proposal={proposal({ sections: written })} onSaved={onSaved} />);
    const smooth = screen.getByRole("button", { name: "Smooth the language" });
    await userEvent.click(smooth);
    expect(await screen.findByRole("alert")).toHaveTextContent("500 became 50");
    expect(call).toHaveBeenCalledWith("/api/proposals/3/polish", "POST");
    await userEvent.click(smooth);
    expect(await screen.findByRole("alert")).toHaveTextContent("Model busy");
    await userEvent.click(smooth);
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
  });

  it("fills the funder's form only when one was chosen, downloads it and reports each heading", async () => {
    stubLocation();
    const report = {
      answered: ["4. Problem Statement"],
      cut: { "5. Proposed strategy": ["54", "Goalpara"] },
      as_written: ["6. Outcomes"],
      add: ["7. Innovation"],
      you_fill: ["PAN Card Number", "Table 3: Budget"],
    };
    const filled = { ...version, n: 2, title: "Version 2, in the Axis form", document_id: 78, shape: "form" as const, report };
    let saved = { summary: proposal().summary, work: proposal().work };
    call.mockImplementation(async (path: string, _method: string, body?: unknown) => {
      if (path === "/api/proposals/3/versions") {
        expect(body).toEqual({ shape: "form" });
        return saved;
      }
      if (path === "/api/documents/78/file") return { url: "https://files.example/v2.docx" };
      return [];
    });
    expect(render(<FinishCard proposal={proposal({ sections: written })} onSaved={vi.fn()} />).queryByRole("button", { name: /form/ })).toBeNull();
    const template = { document_id: 5, url: null, from: "upload" as const, read_at: null };
    saved = { summary: proposal().summary, work: { ...proposal().work, template, versions: [version, filled] } };
    const onSaved = vi.fn();
    const { rerender } = render(<FinishCard proposal={proposal({ sections: written, template })} onSaved={onSaved} />);
    await userEvent.click(screen.getByRole("button", { name: "Download in the Axis form" }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith("https://files.example/v2.docx"));
    rerender(<FinishCard proposal={proposal({ sections: written, template, versions: [version, filled] })} onSaved={onSaved} />);
    const lines = within(screen.getByLabelText("What went into the form"));
    expect(lines.getByText("Answered by Sangam: 1 heading")).toBeInTheDocument();
    expect(lines.getByText("Cut to fit: 1 heading")).toBeInTheDocument();
    expect(lines.getByText("5. Proposed strategy: 54, Goalpara")).toBeInTheDocument();
    expect(lines.getByText("Put in as written: 6. Outcomes")).toBeInTheDocument();
    expect(lines.getByText("Still to add: 7. Innovation, marked [Add]")).toBeInTheDocument();
    expect(lines.getByText("Left for you: 2 headings, marked [You fill] in the file")).toBeInTheDocument();
    expect(screen.getByText("Version 2, in the Axis form")).toBeInTheDocument();
  });

  it("reports a version filled in one call, which has no cuts or parts put in as written", () => {
    const template = { document_id: 5, url: null, from: "upload" as const, read_at: null };
    const report = { answered: ["Organization Name"], add: ["5. Proposed strategy"], you_fill: [] };
    const filled = { ...version, n: 2, title: "Version 2, in the Axis form", document_id: 78, shape: "form" as const, report };
    render(<FinishCard proposal={proposal({ sections: written, template, versions: [version, filled] })} onSaved={vi.fn()} />);
    const lines = within(screen.getByLabelText("What went into the form"));
    expect(lines.getByText("Answered by Sangam: 1 heading")).toBeInTheDocument();
    expect(lines.getByText("Still to add: 5. Proposed strategy, marked [Add]")).toBeInTheDocument();
    expect(lines.queryByText(/Cut to fit|as written|Left for you/)).toBeNull();
  });

  it("has no form button when Sangam's usual order was chosen", () => {
    const template = { document_id: 5, url: null, from: "upload" as const, read_at: null };
    render(<FinishCard proposal={proposal({ sections: written, template, skipped_template: true })} onSaved={vi.fn()} />);
    expect(screen.queryByRole("button", { name: /form/ })).toBeNull();
  });

  it("says when the smoothed wording is out of date", () => {
    const polished = { parts: {}, revs: { A1: 2, A2: 0 }, at: "2026-10-09T00:00:00Z", by: { id: "u", name: "Asha" } };
    render(<FinishCard proposal={proposal({ sections: written, polished })} onSaved={vi.fn()} />);
    expect(screen.getByText(/smoothed on .* by Asha\. 1 part has changed since and will go out as written; smooth it again to include it\./)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Smooth the language again" })).toBeInTheDocument();
  });
});
