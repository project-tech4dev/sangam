/* Small shared presentational components (server-safe). */
import Link from "next/link";
import type { ReactNode } from "react";

export function Breadcrumbs({ items }: { items: { label: string; href?: string }[] }) {
  return (
    <div style={{ fontSize: 12, color: "var(--color-neutral-700)", display: "flex", gap: 6, flexWrap: "wrap" }}>
      {items.map((item, i) => (
        <span key={i} style={{ display: "flex", gap: 6 }}>
          {i > 0 && <span>/</span>}
          {item.href ? (
            <Link href={item.href} style={{ color: "var(--color-accent-700)" }}>
              {item.label}
            </Link>
          ) : (
            <span>{item.label}</span>
          )}
        </span>
      ))}
    </div>
  );
}

export function Tag({
  tone = "neutral",
  children,
}: {
  tone?: "neutral" | "accent" | "accent-2" | "outline" | "track" | "ondark";
  children: ReactNode;
}) {
  return <span className={`tag tag-${tone}`}>{children}</span>;
}

const MARK_COLORS = [
  "var(--color-accent-2-700)",
  "var(--color-accent-700)",
  "var(--color-accent-2-900)",
  "var(--color-accent-900)",
  "var(--color-neutral-700)",
];

export function initialsOf(name: string): string {
  return name
    .replace(/[()[\]]/g, "")
    .split(/\s+/)
    .filter((word) => word && !/^(the|of|and|&)$/i.test(word))
    .slice(0, 2)
    .map((word) => word[0]!.toUpperCase())
    .join("");
}

export function EntityMark({ name, size = 46 }: { name: string; size?: number }) {
  const bg = MARK_COLORS[name.length % MARK_COLORS.length];
  return (
    <div
      aria-hidden
      style={{
        width: size,
        height: size,
        borderRadius: "50%",
        background: bg,
        color: "#fff",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontFamily: "var(--font-heading)",
        fontWeight: 700,
        fontSize: size * 0.34,
        flexShrink: 0,
      }}
    >
      {initialsOf(name)}
    </div>
  );
}

export function ProgressBar({
  pct,
  color = "var(--color-accent-600)",
  height = 10,
}: {
  pct: number;
  color?: string;
  height?: number;
}) {
  const clamped = Math.max(0, Math.min(100, pct));
  return (
    <div className="progress-track" style={{ height }} role="progressbar" aria-valuenow={clamped}>
      <div className="progress-fill" style={{ width: `${clamped}%`, background: color }} />
    </div>
  );
}

const STATUS_STYLES: Record<string, { label: string; cls: string }> = {
  full: { label: "Full profile", cls: "tag-accent" },
  partial: { label: "In vetting", cls: "tag-neutral" },
  verified: { label: "Verified", cls: "tag-accent-2" },
  missing: { label: "Not entered", cls: "tag-neutral" },
  pending: { label: "Pending review", cls: "tag-neutral" },
};

export function StatusChip({ status }: { status: keyof typeof STATUS_STYLES }) {
  const s = STATUS_STYLES[status] ?? STATUS_STYLES.pending;
  return <span className={`tag ${s.cls}`}>{s.label}</span>;
}

/** Big stat numbers; value null renders the honest degraded em-dash state. */
export function StatRail({ stats }: { stats: { value: string | number | null; label: string }[] }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))", gap: 16 }}>
      {stats.map((stat) => (
        <div key={stat.label}>
          <div
            style={{
              fontFamily: "var(--font-heading)",
              fontSize: 28,
              fontWeight: 700,
              color: stat.value === null ? "var(--color-neutral-500)" : "var(--color-text)",
            }}
          >
            {stat.value ?? "—"}
          </div>
          <div style={{ fontSize: 12, color: "var(--color-neutral-700)" }}>
            {stat.value === null ? `${stat.label} — not yet entered` : stat.label}
          </div>
        </div>
      ))}
    </div>
  );
}
