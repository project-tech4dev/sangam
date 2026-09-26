"use client";

import { useEffect, useState } from "react";
import { Tag } from "@/components/ui";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8010";

type Doc = {
  id: number;
  title: string | null;
  doc_type: string | null;
  source_name: string | null;
  source_url: string | null;
  fetched_at: string | null;
};

export function VaultView({ orgs }: { orgs: { id: number; slug: string; name: string }[] }) {
  const [orgSlug, setOrgSlug] = useState(orgs[0]?.slug ?? "");
  const [docs, setDocs] = useState<Doc[] | null>(null);

  useEffect(() => {
    if (!orgSlug) return;
    setDocs(null);
    fetch(`${API}/api/documents?org=${orgSlug}&limit=100`, { headers: { Authorization: "Bearer dev" } })
      .then((res) => res.json())
      .then((page) => setDocs(page.items))
      .catch(() => setDocs([]));
  }, [orgSlug]);

  return (
    <div style={{ flex: 1, minWidth: 0, minHeight: 0, overflowY: "auto", display: "flex", flexDirection: "column", gap: 16 }}>
      <div>
        <div className="eyebrow">Doc vault</div>
        <h2 style={{ fontSize: 20 }}>Documents in the base, per organisation</h2>
      </div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        {orgs.map((org) => (
          <button key={org.id} className="pill" data-active={orgSlug === org.slug} onClick={() => setOrgSlug(org.slug)}>
            {org.name}
          </button>
        ))}
      </div>
      {docs === null ? (
        <div className="muted">Loading…</div>
      ) : docs.length === 0 ? (
        <div className="card">
          <div className="card-title">No documents linked yet</div>
          <div className="card-body">
            The corpus holds 96 documents, but none are linked to this organisation yet — linking
            happens during vetting.
          </div>
        </div>
      ) : (
        <div className="card" style={{ gap: 0, padding: 0 }}>
          {docs.map((doc) => (
            <div
              key={doc.id}
              style={{ display: "flex", gap: 12, alignItems: "center", padding: "12px 18px", borderBottom: "1px solid var(--color-divider)" }}
            >
              <span
                style={{ fontSize: 10, fontWeight: 700, background: "var(--color-neutral-200)", borderRadius: 6, padding: "3px 7px", color: "var(--color-neutral-700)" }}
              >
                {(doc.doc_type ?? "DOC").slice(0, 12).toUpperCase()}
              </span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {doc.title ?? "Untitled document"}
                </div>
                <div className="muted-2" style={{ fontSize: 11.5 }}>
                  {doc.source_name ?? "unknown source"}
                  {doc.fetched_at ? ` · ${new Date(doc.fetched_at).toLocaleDateString("en-IN")}` : ""}
                </div>
              </div>
              <Tag tone="accent-2">In base</Tag>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
