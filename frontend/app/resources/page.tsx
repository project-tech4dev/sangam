import Link from "next/link";
import { Breadcrumbs } from "@/components/ui";

export const metadata = { title: "Resources — Sangam" };

export default function ResourcesPage() {
  return (
    <div className="page" style={{ display: "flex", flexDirection: "column", gap: 20, maxWidth: 960 }}>
      <Breadcrumbs items={[{ label: "Sangam", href: "/registry" }, { label: "Resources" }]} />
      <div>
        <div className="eyebrow">Resources</div>
        <h1 style={{ fontSize: 28 }}>How Sangam works, and the language it uses</h1>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: 16 }}>
        <Link href="/methodology" className="card elev-sm" style={{ textDecoration: "none", color: "inherit" }}>
          <div className="card-kicker">Methodology</div>
          <div className="card-title">How the base is built and how answers are made</div>
          <div className="card-body">
            The three-layer architecture, where the data comes from, the ingest pipeline, how a fit
            score is made, and what confidence means.
          </div>
          <span className="btn btn-ghost" style={{ alignSelf: "flex-start", padding: 0 }}>Read →</span>
        </Link>
        <Link href="/taxonomy" className="card elev-sm" style={{ textDecoration: "none", color: "inherit" }}>
          <div className="card-kicker">Taxonomy</div>
          <div className="card-title">Sectors, SDGs, and occupation tracks</div>
          <div className="card-body">
            The three tag layers every organisation and program carries, and the macro-sector
            crosswalk they map into.
          </div>
          <span className="btn btn-ghost" style={{ alignSelf: "flex-start", padding: 0 }}>Read →</span>
        </Link>
      </div>
    </div>
  );
}
