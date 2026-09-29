import type { ImportSource } from "../lib/types";

const RULE_TEXT: Record<string, string> = {
  open_api: "Open API",
  crawl_allowed: "Crawling allowed",
  crawl_allowed_check_each_site: "Check each site",
  crawl_only_with_permission: "Needs permission",
  no_scraping_manual_entry_allowed: "No scraping",
  manual_entry_only_automation_blocked: "Manual entry only",
  licence_or_paid_access_needed: "Licence needed",
  partner_permission_internal: "Partner data",
  reference_only: "Reference only",
  not_checked: "Not checked",
};

export function SourcePanel({ sources }: { sources: ImportSource[] }) {
  return (
    <section>
      <h2 style={{ fontSize: "var(--fs-lg)", margin: "0 0 4px" }}>Sources</h2>
      <p style={{ fontSize: "var(--fs-sm)", color: "var(--color-muted)", margin: "0 0 14px" }}>
        Only sources whose terms allow it are read automatically. The rest are listed so the reason
        is visible, not so they can be run.
      </p>
      <div style={{ display: "grid", gap: 10 }}>
        {sources.map((s) => (
          <article
            key={s.key}
            style={{
              border: "1px solid var(--color-divider)",
              borderRadius: 10,
              padding: "12px 14px",
              background: s.dispatchable ? "var(--color-surface)" : "transparent",
              opacity: s.dispatchable ? 1 : 0.78,
            }}
          >
            <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
              <strong style={{ fontSize: "var(--fs-md)" }}>{s.name}</strong>
              <span style={{ fontSize: "var(--fs-xs)", color: "var(--color-muted)" }}>{s.host}</span>
              <span
                style={{
                  marginLeft: "auto",
                  fontSize: "var(--fs-xs)",
                  fontWeight: 700,
                  padding: "2px 8px",
                  borderRadius: 999,
                  border: "1px solid var(--color-divider)",
                  color: s.dispatchable ? "var(--color-accent-900)" : "var(--color-muted)",
                }}
              >
                {s.dispatchable ? "runs" : "held"} · {RULE_TEXT[s.access_rule] ?? s.access_rule}
              </span>
            </div>
            <p style={{ fontSize: "var(--fs-sm)", margin: "8px 0 0", lineHeight: 1.5 }}>{s.basis}</p>
            <p style={{ fontSize: "var(--fs-xs)", color: "var(--color-muted)", margin: "6px 0 0" }}>
              yields {s.yields.join(", ")}
              {s.robots_checked_at ? ` · checked ${s.robots_checked_at}` : ""}
            </p>
          </article>
        ))}
      </div>
    </section>
  );
}
