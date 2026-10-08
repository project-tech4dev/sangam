"use client";

import { useMemo, useState } from "react";
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
  manual_aggregator: "Aggregator, named paths",
  internal_research: "Team research, pinned",
};

const CATEGORIES = ["all", "funder", "ngo", "rfp", "media"] as const;
type Cat = (typeof CATEGORIES)[number];

/** Same shape as the Registry's filterable list: query + facets, filtered client-side. */
export function SourcePanel({ sources }: { sources: ImportSource[] }) {
  const [q, setQ] = useState("");
  const [cat, setCat] = useState<Cat>("all");
  const [rule, setRule] = useState("All rules");

  const rules = useMemo(
    () => ["All rules", ...Array.from(new Set(sources.map((s) => s.access_rule))).sort()],
    [sources],
  );

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return sources.filter((s) => {
      if (cat !== "all" && !s.categories.includes(cat)) return false;
      if (rule !== "All rules" && s.access_rule !== rule) return false;
      if (!needle) return true;
      return `${s.name} ${s.key} ${s.host} ${s.basis} ${s.yields.join(" ")}`
        .toLowerCase()
        .includes(needle);
    });
  }, [sources, q, cat, rule]);

  const pulling = sources.filter((s) => s.has_adapter).length;

  return (
    <section style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div>
        <h2 style={{ fontSize: "var(--fs-lg)", margin: "0 0 4px" }}>Sources</h2>
        <p style={{ fontSize: "var(--fs-sm)", color: "var(--color-muted)", margin: 0 }}>
          {sources.length} registered, {pulling} with an adapter that actually pulls. The rest are
          listed so the reason is visible, not so they can be run.
        </p>
      </div>

      <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
        <input
          className="input"
          style={{ maxWidth: 320 }}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search name, host or reason…"
        />
        <div className="seg" role="tablist">
          {CATEGORIES.map((c) => (
            <button
              key={c}
              type="button"
              className="seg-opt"
              data-active={cat === c}
              onClick={() => setCat(c)}
            >
              {c === "all" ? "All" : c}
            </button>
          ))}
        </div>
        <span style={{ marginLeft: "auto", fontSize: "var(--fs-sm)", color: "var(--color-muted)" }}>
          {shown.length} of {sources.length}
        </span>
      </div>

      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        {rules.map((r) => (
          <button
            key={r}
            type="button"
            className="pill"
            data-active={rule === r}
            onClick={() => setRule(r)}
          >
            {RULE_TEXT[r] ?? r}
          </button>
        ))}
      </div>

      {shown.length === 0 ? (
        <div className="card">
          <div className="card-title">Nothing matches</div>
          <div className="card-body">Try a different search, or clear the filters.</div>
        </div>
      ) : (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))",
            gap: 14,
          }}
        >
          {shown.map((s) => (
            <article
              key={s.key}
              style={{
                border: "1px solid var(--color-divider)",
                borderRadius: 10,
                padding: "12px 14px",
                background: s.has_adapter ? "var(--color-surface)" : "transparent",
                opacity: s.dispatchable ? 1 : 0.8,
              }}
            >
              <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
                <strong style={{ fontSize: "var(--fs-md)" }}>{s.name}</strong>
                <span style={{ fontSize: "var(--fs-xs)", color: "var(--color-muted)" }}>
                  {s.host || "checked per site"}
                </span>
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
                  {s.has_adapter ? "pulls" : s.dispatchable ? "permitted" : "held"}
                </span>
              </div>
              <p style={{ fontSize: "var(--fs-sm)", margin: "8px 0 0", lineHeight: 1.5 }}>
                {s.basis}
              </p>
              <p style={{ fontSize: "var(--fs-xs)", color: "var(--color-muted)", margin: "6px 0 0" }}>
                {RULE_TEXT[s.access_rule] ?? s.access_rule} · {s.categories.join(", ")}
                {s.robots_checked_at ? ` · checked ${s.robots_checked_at}` : ""}
              </p>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
