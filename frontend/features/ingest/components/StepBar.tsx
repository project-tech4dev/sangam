const STEPS = ["Start", "Working", "Review", "Done"];

/** Where the person is in an import: Start → Working → Review → Done. */
export function StepBar({ current }: { current: number }) {
  return (
    <ol aria-label="Steps" className="import-steps">
      {STEPS.map((label, i) => {
        const state = i < current ? "done" : i === current ? "now" : "todo";
        return (
          <li key={label} className="import-step" data-state={state} aria-current={state === "now" ? "step" : undefined}>
            <span className="import-step-dot">{state === "done" ? "✓" : i + 1}</span>
            <span className="import-step-label">{label}</span>
            {i < STEPS.length - 1 && <span className="import-step-line" />}
          </li>
        );
      })}
    </ol>
  );
}
