"use client";

import { useState } from "react";
import { Breadcrumbs, Tag } from "@/components/ui";

const SECTORS = [
  { num: "01", name: "Agritech & allied ecosystem", note: "Agriculture, horticulture, livestock, sericulture, NRM-linked livelihoods — the cohort's largest footprint." },
  { num: "02", name: "Built environment & infrastructure", note: "Water structures, sanitation, community infrastructure." },
  { num: "03", name: "Mobility & logistics", note: "Rural transport, market linkage logistics." },
  { num: "04", name: "Retail, commerce & craft", note: "Handloom, handicraft, micro-enterprise, SHG-led commerce." },
  { num: "05", name: "Digital & tech services", note: "Digital access, literacy, and service delivery." },
  { num: "06", name: "Healthcare, wellness & care", note: "Community health, nutrition, disability inclusion, mental health." },
  { num: "07", name: "Production & manufacturing", note: "Food processing, small-scale production units." },
];

export default function TaxonomyPage() {
  const [open, setOpen] = useState<Record<string, boolean>>({ "01": true });

  return (
    <div className="page" style={{ display: "flex", flexDirection: "column", gap: 22, maxWidth: 1060 }}>
      <Breadcrumbs items={[{ label: "Sangam", href: "/registry" }, { label: "Resources", href: "/resources" }, { label: "Taxonomy" }]} />
      <div>
        <div className="eyebrow">Taxonomy</div>
        <h1 style={{ fontSize: 28 }}>Three tag layers, one crosswalk</h1>
        <p className="muted" style={{ maxWidth: 640 }}>
          Every organisation and program carries up to three kinds of tags: <strong>SDGs</strong>{" "}
          (the global language funders report in), a <strong>sector label</strong> (what the work
          is), and an <strong>occupation track</strong> (where the livelihoods it creates sit).
          Enabling work — capacity building, governance, entitlements — deliberately gets no
          occupation cell.
        </p>
      </div>

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <Tag tone="accent-2">Formal — NIC / corporate</Tag>
        <Tag tone="accent">Gig / platform</Tag>
        <Tag tone="track">Informal — eShram / Vishwakarma</Tag>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {SECTORS.map((sector) => {
          const isOpen = open[sector.num] ?? false;
          return (
            <div key={sector.num} className="card" style={{ gap: 6, padding: 18 }}>
              <button
                onClick={() => setOpen({ ...open, [sector.num]: !isOpen })}
                style={{ display: "flex", alignItems: "center", gap: 12, background: "none", border: "none", cursor: "pointer", fontFamily: "var(--font-heading)", fontSize: 16, fontWeight: 600, color: "var(--color-text)", padding: 0, textAlign: "left" }}
              >
                <span className="muted-2" style={{ fontFamily: "var(--font-heading)" }}>{sector.num}</span>
                {sector.name}
                <span style={{ marginLeft: "auto", color: "var(--color-neutral-500)" }}>{isOpen ? "−" : "+"}</span>
              </button>
              {isOpen && <div className="card-body">{sector.note}</div>}
            </div>
          );
        })}
      </div>

      <div className="card" style={{ background: "var(--color-accent-2-100)", border: "none" }}>
        <div className="card-body" style={{ color: "var(--color-accent-2-900)" }}>
          The crosswalk is a working draft: sector tags in the Registry come from source data
          (Darpan working sectors, funder focus areas) and are normalised during vetting.
        </div>
      </div>
    </div>
  );
}
