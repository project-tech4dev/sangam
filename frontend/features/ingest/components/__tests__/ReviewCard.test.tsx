import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReviewAnswer } from "../../lib/types";
import { review, status, stubFetch } from "./fakes";

type Config = {
  enabled: (e: { value: unknown }) => boolean;
  render: (p: { event: { value: unknown }; resolve: (v: unknown) => void }) => ReactElement;
};
const pause = vi.hoisted(() => ({ event: null as { value: unknown } | null, resolve: vi.fn() }));

vi.mock("@copilotkit/react-core/v2", () => ({
  useInterrupt: (cfg: Config) => (pause.event && cfg.enabled(pause.event) ? cfg.render({ event: pause.event, resolve: pause.resolve }) : null),
}));
vi.mock("@/lib/api/auth-headers", () => ({ authHeaders: async () => ({}) }));

import { Answer, Missing } from "../ReviewFields";
import { ReviewCard, type PausedQuestion } from "../ReviewCard";
import { SaveQuestions, pausedSave } from "../SaveQuestions";
import { ScreenReview } from "../ScreenReview";

const answer = (over: Partial<ReviewAnswer> = {}): ReviewAnswer => ({
  concept: "budget",
  topic: "CSR budget",
  year: "2024-25",
  facts: [{ label: "Spent", value: 25000000, money: true }],
  tag: "confirmed",
  quote: "We spent 2.5 crore",
  source_url: "https://kabil.org/csr",
  source_name: "CSR report",
  ...over,
});

const amountQuestion: PausedQuestion = {
  id: "q1",
  case: 3,
  table: "funder_budgets",
  label: "2024-25",
  changes: { amount_inr: { old: 100, new: 200 } },
  stored_as_of: "2023-01-01",
  choices: ["keep", "update", "odd_choice"],
};

beforeEach(() => {
  pause.event = null;
  pause.resolve.mockReset();
});
afterEach(() => vi.unstubAllGlobals());

describe("ReviewCard", () => {
  it("shows loading, then what was found, and saves with no questions to answer", async () => {
    stubFetch({ "/research/kabil/review": review({ answers: [answer(), answer({ tag: "self_reported" })], missing: [{ concept: "m", topic: "Board", tag: "not_mentioned", detail: "" }] }) });
    const onDecide = vi.fn();
    render(<ReviewCard slug="kabil" onDecide={onDecide} />);
    expect(screen.getByText("Getting the answers ready…")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save 1 organisation" })).toBeDisabled();

    expect(await screen.findByText("Funder · New to Sangam")).toBeInTheDocument();
    expect(screen.getByText("1 of 3 confirmed")).toBeInTheDocument();
    expect(screen.getByText("Nothing is saved until you choose.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "See answers" }));
    expect(screen.getAllByText("₹2.5 crore", { exact: false })).toHaveLength(2);
    expect(screen.getByText("Board")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Hide answers" }));
    expect(screen.queryByText("Board")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Save 1 organisation" }));
    expect(onDecide).toHaveBeenCalledWith({
      type: "edit",
      edited_action: { name: "promote_research", args: { slug: "kabil", decisions: {} } },
    });
    expect(screen.getByRole("button", { name: "Saving…" })).toBeDisabled();
  });

  it("waits for every question, then sends the answers", async () => {
    stubFetch({
      "/review": review({
        questions: [
          { id: "q1", case: 3, topic: "Budget", about: "2024-25", fields: [{ label: "Amount", old: 1e5, new: [1, 2], money: true }], stored_as_of: null, new_as_of: "2024-04-01", stored_name: null, new_name: null, choices: [{ value: "keep", label: "Keep" }, { value: "update", label: "Update" }, { value: "odd_choice", label: "Odd one" }] },
        ],
      }),
    });
    const onDecide = vi.fn();
    render(<ReviewCard slug="kabil" questions={[amountQuestion, { id: "q2", case: 4, table: "funders", label: "", stored_name: "KABIL Ltd", new_name: "Kabil", choices: ["update", "new", "skip"] }]} onDecide={onDecide} />);

    expect(await screen.findByText("Budget · 2024-25")).toBeInTheDocument();
    // The review words the question; the payload says which choices exist.
    expect(screen.getByText(/Amount: Sangam already says “₹1 lakh” \(no date\)\. The new research says “1, 2” \(from 2024-04-01\)/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Odd one" })).toBeInTheDocument();
    expect(screen.getByText("Is this the same organisation?")).toBeInTheDocument();
    expect(screen.getByText(/The research found “Kabil”\. Sangam has “KABIL Ltd”/)).toBeInTheDocument();
    expect(screen.getByText("Answer 2 questions above first.")).toBeInTheDocument();
    const save = screen.getByRole("button", { name: "Save 1 organisation" });
    expect(save).toBeDisabled();

    await userEvent.click(screen.getByRole("button", { name: "Use the new answer" }));
    expect(screen.getByText("Answer the question above first.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "No, they're different" }));
    expect(screen.getByRole("button", { name: "No, they're different" })).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(save);
    expect(onDecide).toHaveBeenCalledWith({
      type: "edit",
      edited_action: { name: "promote_research", args: { slug: "kabil", decisions: { q1: "update", q2: "new" } } },
    });
  });

  it("words the payload's own question when the review cannot load, and can decline", async () => {
    stubFetch({ "/review": status(500) });
    const onDecide = vi.fn();
    render(<ReviewCard slug="kabil" questions={[amountQuestion]} onDecide={onDecide} />);
    expect(await screen.findByText("Sangam couldn't load the answers. You can still save or not.")).toBeInTheDocument();
    expect(screen.getByText("Funder budgets · 2024-25")).toBeInTheDocument();
    expect(screen.getByText(/Amount inr: Sangam already says “100” \(from 2023-01-01\)/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Odd choice" })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("checkbox", { name: "Save kabil" }));
    expect(screen.queryByText("Funder budgets · 2024-25")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Continue without saving" }));
    expect(onDecide).toHaveBeenCalledWith({ type: "reject", message: "Staff chose not to save this research." });
  });

  it("shows a refused save's reason and lets the person try again", async () => {
    stubFetch({ "/review": review() });
    const onDecide = vi.fn().mockRejectedValueOnce(new Error("Row changed since")).mockRejectedValueOnce("plain");
    render(<ReviewCard slug="kabil" onDecide={onDecide} inline />);
    expect(screen.queryByText("Here's what Sangam found")).not.toBeInTheDocument();
    const save = await screen.findByRole("button", { name: "Save 1 organisation" });
    await waitFor(() => expect(save).toBeEnabled());
    await userEvent.click(save);
    expect(await screen.findByText("Row changed since")).toBeInTheDocument();
    expect(save).toBeEnabled();
    await userEvent.click(save);
    expect(await screen.findByText("plain")).toBeInTheDocument();
  });

  it("saves everything in the run without fetching a review when there is no slug", async () => {
    const fetchMock = stubFetch({});
    const onDecide = vi.fn();
    render(<ReviewCard slug="" onDecide={onDecide} />);
    expect(screen.getByText("Everything researched in this run")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Save everything" }));
    expect(onDecide).toHaveBeenCalledOnce();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("pages a long list of answers and notes an existing NGO is only filled in", async () => {
    const many = Array.from({ length: 12 }, (_, i) => answer({ concept: `c${i}`, topic: `Topic ${i}` }));
    stubFetch({ "/review": review({ kind: "org", name: "Pratham", existing: true, answers: many }) });
    render(<ReviewCard slug="pratham" onDecide={vi.fn()} />);
    expect(await screen.findByText("NGO · Already in Sangam")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "See answers" }));
    expect(screen.queryByText(/Topic 11/)).not.toBeInTheDocument();
    expect(screen.getByText(/Sangam already has a profile for Pratham/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Show all 12" }));
    expect(screen.getByText(/Topic 11/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Show fewer" }));
    expect(screen.queryByText(/Topic 11/)).not.toBeInTheDocument();
  });
});

describe("Answer and Missing", () => {
  it("opens the proof with a web link for a confirmed answer", async () => {
    render(<Answer answer={answer({ facts: [{ label: null, value: "Yes", money: false }], year: null })} />);
    expect(screen.getByText("Yes")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Confirmed/ }));
    expect(screen.getByText("“We spent 2.5 crore”")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "CSR report" })).toHaveAttribute("href", "https://kabil.org/csr");
  });

  it("explains a self-reported answer from the person's own document", async () => {
    render(<Answer answer={answer({ tag: "self_reported", facts: [], private: true, held: true, quote: "" })} />);
    expect(screen.getByText("Found")).toBeInTheDocument();
    expect(screen.getByText("From your documents · not saved")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Self-reported/ }));
    expect(screen.getByText(/what they say about themselves/)).toBeInTheDocument();
    expect(screen.getByText(/not saved to Sangam/)).toBeInTheDocument();
    expect(screen.getByText("Your document: CSR report")).toBeInTheDocument();
  });

  it("never links a spreadsheet or a non-web source", async () => {
    const { unmount } = render(<Answer answer={answer({ source_url: "https://staff-sources.sangam.invalid/x" })} />);
    await userEvent.click(screen.getByRole("button", { name: /Confirmed/ }));
    expect(screen.getByText("Your team's spreadsheet")).toBeInTheDocument();
    unmount();
    const r = render(<Answer answer={answer({ source_url: "javascript:alert(1)", source_name: "" })} />);
    await userEvent.click(screen.getByRole("button", { name: /Confirmed/ }));
    expect(screen.getByText("Source")).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    r.unmount();
    render(<Answer answer={answer({ private: true, source_url: "", })} />);
    await userEvent.click(screen.getByRole("button", { name: /Confirmed/ }));
    expect(screen.queryByText(/Your document/)).not.toBeInTheDocument();
    expect(screen.getByText("From your documents")).toBeInTheDocument();
  });

  it("says why a topic is missing", async () => {
    const { unmount } = render(<Missing m={{ concept: "a", topic: "Board", tag: "couldnt_read", detail: "" }} />);
    expect(screen.getAllByText(/Couldn't read/)).toHaveLength(2);
    await userEvent.click(screen.getByRole("button", { name: /Couldn't read/ }));
    expect(screen.getByText(/was a scan or blocked/)).toBeInTheDocument();
    unmount();
    render(<Missing m={{ concept: "a", topic: "Board", tag: "not_mentioned", detail: "" }} reason="Not on their website" />);
    expect(screen.getByText("Not on their website")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Not mentioned/ }));
    expect(screen.getByText("Sangam didn't find this in anything it read.")).toBeInTheDocument();
  });
});

describe("ScreenReview", () => {
  it("saves from the screen with the person's answers", async () => {
    const result = { slug: "kabil", entity: { kind: "funder", id: 4, name: "KABIL", status: null }, promotion_id: 1, written: 3, held: 0, reasons: [] };
    const fetchMock = stubFetch({ "/review": review(), "/research/kabil/save": result });
    const onSaved = vi.fn();
    render(<ScreenReview slug="kabil" onSaved={onSaved} onDeclined={vi.fn()} />);
    await userEvent.click(await screen.findByRole("button", { name: "Save 1 organisation" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(result));
    const save = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/save"))!;
    expect(save[1]).toMatchObject({ method: "POST", body: JSON.stringify({ decisions: {} }) });
  });

  it("keeps the card open with the reason when nothing was written", async () => {
    stubFetch({ "/review": review(), "/save": { slug: "kabil", entity: null, promotion_id: null, written: 0, held: 0, reasons: ["A close name is unanswered."] } });
    const onSaved = vi.fn();
    render(<ScreenReview slug="kabil" onSaved={onSaved} onDeclined={vi.fn()} />);
    await userEvent.click(await screen.findByRole("button", { name: "Save 1 organisation" }));
    expect(await screen.findByText("Nothing was saved. A close name is unanswered.")).toBeInTheDocument();
    expect(onSaved).not.toHaveBeenCalled();
  });

  it("shows the backend's refusal", async () => {
    stubFetch({ "/review": review(), "/save": status(409, { detail: "Already saved" }) });
    render(<ScreenReview slug="kabil" onSaved={vi.fn()} onDeclined={vi.fn()} />);
    await userEvent.click(await screen.findByRole("button", { name: "Save 1 organisation" }));
    expect(await screen.findByText("Already saved")).toBeInTheDocument();
  });

  it("declines without calling the backend", async () => {
    const fetchMock = stubFetch({ "/review": review() });
    const onDeclined = vi.fn();
    render(<ScreenReview slug="kabil" onSaved={vi.fn()} onDeclined={onDeclined} />);
    await userEvent.click(await screen.findByRole("checkbox", { name: "Save KABIL" }));
    await userEvent.click(screen.getByRole("button", { name: "Continue without saving" }));
    expect(onDeclined).toHaveBeenCalledOnce();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe("SaveQuestions", () => {
  const paused = { action_requests: [{ name: "promote_research", args: { slug: "kabil" }, questions: [amountQuestion] }] };

  it("reads a paused promote_research and nothing else", () => {
    expect(pausedSave(JSON.stringify(paused))).toEqual({ slug: "kabil", questions: [amountQuestion] });
    expect(pausedSave({ action_requests: [{ name: "promote_research", questions: [] }] })).toEqual({ slug: "", questions: [] });
    expect(pausedSave("{bad")).toBeNull();
    expect(pausedSave({ action_requests: [{ name: "promote_research" }] })).toBeNull();
    expect(pausedSave(null)).toBeNull();
  });

  it("resolves the pause with the decision and the slug it belongs to", async () => {
    stubFetch({ "/review": status(404) });
    pause.event = { value: paused };
    const onPaused = vi.fn();
    render(<SaveQuestions agentId="a" onPaused={onPaused} />);
    expect(onPaused).toHaveBeenCalledWith(true);
    await userEvent.click(await screen.findByRole("button", { name: "Keep what Sangam has" }));
    await userEvent.click(screen.getByRole("button", { name: "Save 1 organisation" }));
    expect(pause.resolve).toHaveBeenCalledWith({
      decisions: [{ type: "edit", edited_action: { name: "promote_research", args: { slug: "kabil", decisions: { q1: "keep" } } } }],
      slug: "kabil",
    });
  });

  it("stays empty for another pause", () => {
    pause.event = { value: { action_requests: [{ name: "choose_sources" }] } };
    const { container } = render(<SaveQuestions agentId="a" onPaused={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });
});
