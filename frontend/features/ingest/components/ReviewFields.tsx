"use client";

import { useState } from "react";
import { formatInr } from "@/lib/format";
import type { ReviewAnswer, ReviewFact, ReviewMissing } from "../lib/types";

// Findings from a staff workbook cite this made-up host (backend app/ingest/staff_sources.py); it is not a page.
const STAFF_SOURCE = "https://staff-sources.sangam.invalid/";
const NOTE = {
  self_reported: "This is what they say about themselves. There's no certificate, number or document to back it up.",
  not_mentioned: "Sangam didn't find this in anything it read.",
  couldnt_read: "A page that might say was a scan or blocked, so Sangam couldn't read it. Worth opening it yourself.",
};

const fact = (f: ReviewFact) => {
  const value = f.money && typeof f.value === "number" ? formatInr(f.value) : String(f.value);
  return f.label ? `${f.label}: ${value}` : value;
};

// The backend keeps findings to http(s); checked again here, since the link is from the open web.
const isWebLink = (url: string) => /^https?:\/\//i.test(url);

function Source({ answer }: { answer: ReviewAnswer }) {
  if (!answer.source_url) return null;
  if (answer.source_url.startsWith(STAFF_SOURCE)) return <span className="review-source">Your team&apos;s spreadsheet</span>;
  if (!isWebLink(answer.source_url)) return <span className="review-source">{answer.source_name || "Source"}</span>;
  return (
    <a className="review-source" href={answer.source_url} target="_blank" rel="noopener noreferrer">
      {answer.source_name || "Source"}
    </a>
  );
}

export function Answer({ answer }: { answer: ReviewAnswer }) {
  const [open, setOpen] = useState(false);
  const confirmed = answer.tag === "confirmed";
  return (
    <div className="review-field">
      <div className="review-field-head">
        <div className="review-field-text">
          <span className="review-field-q">
            {answer.topic}
            {answer.year && ` · ${answer.year}`}
          </span>
          <span className="review-field-a">{answer.facts.length > 0 ? answer.facts.map(fact).join(" · ") : "Found"}</span>
        </div>
        <button
          type="button"
          className={`tag review-field-tag ${confirmed ? "tag-accent-2" : "tag-accent"}`}
          aria-expanded={open}
          onClick={() => setOpen(!open)}
        >
          {confirmed ? "Confirmed" : "Self-reported"} ›
        </button>
      </div>
      {open && (
        <div className="review-proof">
          {answer.quote && <p>“{answer.quote}”</p>}
          {!confirmed && <p className="review-proof-note">{NOTE.self_reported}</p>}
          <Source answer={answer} />
        </div>
      )}
    </div>
  );
}

export function Missing({ m, reason }: { m: ReviewMissing; reason?: string }) {
  const [open, setOpen] = useState(false);
  const unread = m.tag === "couldnt_read";
  return (
    <div className="review-field">
      <div className="review-field-head">
        <div className="review-field-text">
          <span className="review-field-q">{m.topic}</span>
          <span className="review-field-a">{reason || (unread ? "Couldn't read" : "Not mentioned")}</span>
        </div>
        <button
          type="button"
          className={`tag review-field-tag ${unread ? "tag-outline" : "tag-neutral"}`}
          aria-expanded={open}
          onClick={() => setOpen(!open)}
        >
          {unread ? "Couldn't read" : "Not mentioned"} ›
        </button>
      </div>
      {open && (
        <div className="review-proof">
          <p className="review-proof-note">{NOTE[m.tag]}</p>
        </div>
      )}
    </div>
  );
}
