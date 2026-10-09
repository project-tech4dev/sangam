import Link from "next/link";
import { EntityMark } from "@/components/ui/primitives";
import type { ResearchRecord } from "../lib/types";
import { kindLabel, profileHref, researchState } from "../lib/words";

const day = (iso: string) => new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short" });

/** Every organisation researched, saved to a profile or not. */
export function ResearchedRecently({ items }: { items: ResearchRecord[] }) {
  if (items.length === 0) return null;
  return (
    <section className="import-section">
      <div className="import-section-head">
        <h2 className="import-h2">Researched recently</h2>
        <span className="import-hint">Everything Sangam found is kept, even if you didn&apos;t save it to a profile.</span>
      </div>
      <div className="import-shelf">
        {items.map((r) => {
          const name = r.canonical_name ?? r.entity_name;
          const state = researchState(r);
          const href = profileHref(r);
          return (
            <div key={r.id} className="import-shelf-row">
              <EntityMark name={name} size={32} />
              <div className="import-shelf-name">
                <strong>{name}</strong>
                <span className="import-hint">
                  {kindLabel(r.entity_kind)} · {r.fact_count} answers · {day(r.researched_at)}
                </span>
              </div>
              <span className={`tag ${state.tag}`}>{state.label}</span>
              {href && (
                <Link href={href} className="import-link">
                  Open profile
                </Link>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
