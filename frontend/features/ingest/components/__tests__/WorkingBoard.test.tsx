import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { TraceStep } from "@/lib/useAgentChat";
import { WorkingBoard } from "../WorkingBoard";

let n = 0;
const step = (tool: string, args: unknown, result: string | null, extra: Partial<TraceStep> = {}): TraceStep => ({
  id: `s${++n}`,
  tool,
  args,
  result,
  running: result === null,
  ...extra,
});
const researcher = (description: string, result: string | null, extra: Partial<TraceStep> = {}) =>
  step("task", { description, subagent_type: "entity-researcher" }, result, extra);
const ready = (name: string) => researcher(`${name} — x`, JSON.stringify({ status: "ready", concepts_found: ["a", "b"] }), { doneAt: 1 });
const sources = step("choose_sources", {}, "- public websites: yes\n- Sangam's library: no");

describe("WorkingBoard", () => {
  it("renders nothing before a run has a step", () => {
    const { container } = render(<WorkingBoard steps={[]} running={false} paused={false} laneOwners={{}} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows a researcher at work, its pages, and the overall totals", async () => {
    const kabil = researcher("KABIL — find funding", null, { running: true });
    const steps = [
      sources,
      kabil,
      step("research_goals", { name: "KABIL" }, "a -> x\nb -> y\n", { lane: "A", doneAt: 0.5 }),
      step("read_page", { url: "https://kabil.org/about/" }, "text", { lane: "A", doneAt: 1 }),
      ready("Pratham"),
    ];
    render(<WorkingBoard steps={steps} running paused={false} laneOwners={{ A: kabil.id }} />);
    expect(screen.getByRole("heading", { name: "Scout is researching 2 organisations" })).toBeInTheDocument();
    expect(screen.getByText(/usually takes a few minutes/)).toBeInTheDocument();
    expect(screen.getByText("Reading from: Public websites")).toBeInTheDocument();
    expect(screen.getByText("1 of 2")).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Overall progress" })).toBeInTheDocument();
    expect(screen.getByText("✓ Ready")).toBeInTheDocument();
    expect(screen.getByText("Just now")).toBeInTheDocument();

    const kabilRow = screen.getByRole("button", { name: /KABIL/ });
    expect(kabilRow).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(kabilRow);
    expect(screen.getByText("What Sangam read (1)")).toBeInTheDocument();
    expect(screen.getByText("/about")).toBeInTheDocument();
    // A row with no pages read has nothing to open.
    expect(screen.getByRole("button", { name: /Pratham/ })).toBeDisabled();
  });

  it("says saving is under way once every organisation is ready and the run goes on", () => {
    render(<WorkingBoard steps={[ready("A"), ready("B")]} running paused={false} laneOwners={{}} />);
    expect(screen.getByRole("heading", { name: "Saving to Sangam…" })).toBeInTheDocument();
    expect(screen.getByText("Writing what you approved into the profiles.")).toBeInTheDocument();
  });

  it("says research is finished, unsaved, once the run stops", () => {
    render(<WorkingBoard steps={[ready("A")]} running={false} paused={false} laneOwners={{}} />);
    expect(screen.getByRole("heading", { name: "Research finished" })).toBeInTheDocument();
    expect(screen.getByText(/Nothing is saved yet/)).toBeInTheDocument();
  });

  it("names each researcher's end state", () => {
    const steps = [
      researcher("A — x", null),
      researcher("B — x", JSON.stringify({ status: "not_found" })),
      researcher("C — x", JSON.stringify({ status: "wrong_entity" })),
    ];
    const { rerender } = render(<WorkingBoard steps={steps} running={false} paused={false} laneOwners={{}} />);
    expect(screen.getByText("Stopped")).toBeInTheDocument();
    expect(screen.getByText("Not found")).toBeInTheDocument();
    expect(screen.getByText("Different one")).toBeInTheDocument();
    rerender(<WorkingBoard steps={steps} running={false} paused laneOwners={{}} />);
    expect(screen.getByText("Paused")).toBeInTheDocument();
    rerender(<WorkingBoard steps={[researcher("A — x", null)]} running paused={false} laneOwners={{}} />);
    expect(screen.getByText("Starting")).toBeInTheDocument();
  });

  it("with no organisations, says the step in flight", () => {
    const { rerender } = render(<WorkingBoard steps={[]} running paused={false} laneOwners={{}} />);
    expect(screen.getByRole("heading", { name: "Scout is working" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Getting started");
    expect(screen.getByText("0")).toBeInTheDocument();

    rerender(<WorkingBoard steps={[sources]} running paused={false} laneOwners={{}} />);
    expect(screen.getByRole("status")).toHaveTextContent("Deciding what to do next");
    rerender(<WorkingBoard steps={[step("task", { subagent_type: "workbook-reader" }, null)]} running paused={false} laneOwners={{}} />);
    expect(screen.getByRole("status")).toHaveTextContent("Researching");
    rerender(<WorkingBoard steps={[step("run_import_now", {}, null)]} running paused={false} laneOwners={{}} />);
    expect(screen.getByRole("status").textContent).not.toBe("");

    rerender(<WorkingBoard steps={[sources]} running={false} paused laneOwners={{}} />);
    expect(screen.getByRole("heading", { name: "Paused — waiting for you" })).toBeInTheDocument();
    rerender(<WorkingBoard steps={[sources]} running={false} paused={false} laneOwners={{}} compact />);
    expect(screen.queryByRole("heading")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Finished");
    expect(screen.getByText("Reading from: Public websites")).toBeInTheDocument();
  });
});
