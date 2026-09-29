import type { TraceStep } from "@/lib/useAgentChat";

/** The name the main agent put before the em dash, e.g. "KABIL — find …". */
function subjectOf(args: any): string {
  const description: string = args?.description ?? "";
  const [head] = description.split(/\s[—–-]\s/, 1);
  const subject = (head ?? "").trim();
  if (subject && subject.length <= 60) return subject;
  return description.slice(0, 60) || "a task";
}

function briefOf(args: any): string {
  const description: string = args?.description ?? "";
  const parts = description.split(/\s[—–-]\s/);
  return (parts.length > 1 ? parts.slice(1).join(" — ") : description).trim();
}

/** One box per subagent, so it is visible that several are working at once. */
export function SubagentBoard({ steps }: { steps: TraceStep[] }) {
  if (steps.length === 0) return null;
  const running = steps.filter((s) => s.running).length;
  return (
    <section
      style={{
        border: "1px solid var(--color-divider)",
        borderRadius: 10,
        padding: "12px 14px",
        background: "var(--color-surface)",
      }}
    >
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 10 }}>
        <strong style={{ fontSize: "var(--fs-sm)" }}>
          {steps.length} researcher{steps.length === 1 ? "" : "s"}
        </strong>
        <span style={{ fontSize: "var(--fs-xs)", color: "var(--color-muted)" }}>
          {running > 0 ? `${running} still working` : "all finished"} · one organisation each,
          separate context
        </span>
      </div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(230px, 1fr))",
          gap: 10,
        }}
      >
        {steps.map((step) => (
          <article
            key={step.id}
            style={{
              border: "1px solid var(--color-divider)",
              borderLeft: `3px solid ${step.running ? "var(--color-accent-900)" : "var(--color-divider)"}`,
              borderRadius: 8,
              padding: "9px 11px",
              background: "var(--color-bg, transparent)",
            }}
          >
            <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
              <strong style={{ fontSize: "var(--fs-sm)" }}>{subjectOf(step.args)}</strong>
              <span
                style={{
                  marginLeft: "auto",
                  fontSize: "var(--fs-xs)",
                  color: step.running ? "var(--color-accent-900)" : "var(--color-muted)",
                }}
              >
                {step.running ? "researching…" : "done"}
              </span>
            </div>
            <p
              style={{
                margin: "5px 0 0",
                fontSize: "var(--fs-xs)",
                color: "var(--color-muted)",
                lineHeight: 1.45,
              }}
            >
              {briefOf(step.args).slice(0, 130)}
            </p>
          </article>
        ))}
      </div>
    </section>
  );
}
