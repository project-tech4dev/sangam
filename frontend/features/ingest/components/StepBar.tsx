const STEPS = ["Start", "Working", "Review", "Done"];

/** Where the person is: an import's Start → Working → Review → Done, or the steps given. */
export function StepBar({ current, size, steps = STEPS }: { current: number; size?: "sm"; steps?: string[] }) {
  return (
    <ol aria-label="Steps" className="import-steps" data-size={size}>
      {steps.map((label, i) => {
        const state = i < current ? "done" : i === current ? "now" : "todo";
        return (
          <li key={label} className="import-step" data-state={state} aria-current={state === "now" ? "step" : undefined}>
            <span className="import-step-dot">{state === "done" ? "✓" : i + 1}</span>
            <span className="import-step-label">{label}</span>
            {i < steps.length - 1 && <span className="import-step-line" />}
          </li>
        );
      })}
    </ol>
  );
}
