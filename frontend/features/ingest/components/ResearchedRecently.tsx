"use client";

import Link from "next/link";
import { useState } from "react";
import { EntityMark } from "@/components/ui/primitives";
import { deleteResearch, undoSave } from "../lib/staffActions";
import { ScreenReview } from "./ScreenReview";
import type { ResearchRecord } from "../lib/types";
import { kindLabel, profileHref, researchState } from "../lib/words";

const day = (iso: string) => new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short" });

/** Every organisation researched, saved to a profile or not. Unsaved research can be reviewed and saved here;
 *  staff can also undo a save, or delete unsaved research. */
export function ResearchedRecently({
  items,
  staff = false,
  onChanged,
  limit = 5,
}: {
  items: ResearchRecord[];
  staff?: boolean;
  onChanged?: () => void;
  /** How many show before "Show all". */
  limit?: number;
}) {
  const [showAll, setShowAll] = useState(false);
  const [busy, setBusy] = useState<number | null>(null);
  const [failed, setFailed] = useState<{ id: number; text: string } | null>(null);
  const [reviewing, setReviewing] = useState<number | null>(null);
  if (items.length === 0) return null;

  async function act(r: ResearchRecord, name: string) {
    const undo = r.promotion_id != null;
    const ask = undo
      ? `Undo saving ${name}? What it added to Sangam is removed and what it changed is put back.`
      : `Delete the research on ${name}? It was not saved to Sangam.`;
    if (!window.confirm(ask)) return;
    setBusy(r.id);
    setFailed(null);
    try {
      await (undo ? undoSave(r.promotion_id!) : deleteResearch(r.slug));
      onChanged?.();
    } catch (e) {
      setFailed({ id: r.id, text: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="import-section">
      <div className="import-section-head">
        <h2 className="import-h2">Researched recently</h2>
        <span className="import-hint">Everything Sangam found is kept, even if you didn&apos;t save it to a profile.</span>
      </div>
      <div className="import-shelf">
        {(showAll ? items : items.slice(0, limit)).map((r) => {
          const name = r.canonical_name ?? r.entity_name;
          const state = researchState(r);
          const href = profileHref(r);
          const reviewable = !r.saved_at && r.status !== "not_found" && r.status !== "wrong_entity";
          return (
            <div key={r.id} className="import-shelf-item">
              <div className="import-shelf-row">
                <EntityMark name={name} size={32} />
                <div className="import-shelf-name">
                  <strong title={name}>{name}</strong>
                  <span className="import-hint">
                    {kindLabel(r.entity_kind)} · {r.fact_count} answers · {day(r.researched_at)}
                    {r.saved_by && ` · saved by ${r.saved_by}`}
                  </span>
                  {failed?.id === r.id && <span className="import-error">{failed.text}</span>}
                </div>
                <span className={`tag ${state.tag} import-shelf-tag`}>{state.label}</span>
                <div className="import-shelf-actions">
                  {href && (
                    <Link href={href} className="import-link">
                      Open profile
                    </Link>
                  )}
                  {reviewable && reviewing !== r.id && (
                    <button type="button" className="import-link" onClick={() => setReviewing(r.id)}>
                      Review &amp; save
                    </button>
                  )}
                  {staff && (
                    <button type="button" className="import-link" disabled={busy === r.id} onClick={() => act(r, name)}>
                      {busy === r.id ? "Working…" : r.promotion_id != null ? "Undo save" : "Delete"}
                    </button>
                  )}
                </div>
              </div>
              {reviewing === r.id && (
                <div className="import-shelf-review">
                  <ScreenReview
                    slug={r.slug}
                    onSaved={() => {
                      setReviewing(null);
                      onChanged?.();
                    }}
                    onDeclined={() => setReviewing(null)}
                  />
                </div>
              )}
            </div>
          );
        })}
      </div>
      {items.length > limit && (
        <button type="button" className="import-link" onClick={() => setShowAll(!showAll)}>
          {showAll ? "Show fewer" : `Show all (${items.length})`}
        </button>
      )}
    </section>
  );
}
