import { expect, it } from "vitest";
import { citationTarget, extractCitations, type RegistryIndex } from "@/features/ask/lib/citations";
import { phasesFor } from "@/features/ask/lib/phases";
import { EXAMPLE_QUESTIONS, SAMPLE_ANSWER, SAMPLE_CRITERIA, SAMPLE_INDEX, SAMPLE_QUESTION, SAMPLE_TRACE } from "@/features/ask/preview/sample";

const index = {
  orgs: new Map(SAMPLE_INDEX.orgs),
  funders: new Map(SAMPLE_INDEX.funders),
  scores: new Map(SAMPLE_INDEX.scores),
  activities: new Map(),
} as unknown as RegistryIndex;

it("every marker in the sample answer resolves through the sample index", () => {
  for (const { kind, id } of extractCitations(SAMPLE_ANSWER)) {
    expect(citationTarget(kind, id, index).href, `${kind}:${id}`).not.toBeNull();
  }
});

it("the criteria add up to the score the answer states", () => {
  const total = SAMPLE_CRITERIA.reduce((sum, c) => sum + c.score, 0);
  expect(SAMPLE_ANSWER).toContain(`**${total} out of 100**`);
  expect(SAMPLE_CRITERIA.reduce((sum, c) => sum + c.max, 0)).toBe(100);
});

it("the trace renders as finished phases and the sample is the first example", () => {
  const phases = phasesFor({ id: "p", question: SAMPLE_QUESTION, steps: SAMPLE_TRACE, answer: SAMPLE_ANSWER, streaming: false });
  expect(phases.every((p) => p.state === "done")).toBe(true);
  expect(EXAMPLE_QUESTIONS[0]).toBe(SAMPLE_QUESTION);
});
