"use client";

import { Bookmark, CalendarClock, ExternalLink, IndianRupee, MapPin, MessageSquare, X } from "lucide-react";
import { dayMonthYear, formatInr } from "@/lib/format";
import { safeHref } from "@/features/registry/profile/shared";
import type { FeedCall } from "./api";

export const SOON_DAYS = 30;
const URGENT_DAYS = 14;

/** Whole days from today to the deadline; negative once it has passed. */
export function daysLeft(deadline: string | null, today = new Date()): number | null {
  if (!deadline) return null;
  const [y, m, d] = deadline.split("-").map(Number);
  const start = Date.UTC(today.getFullYear(), today.getMonth(), today.getDate());
  return Math.round((Date.UTC(y, m - 1, d) - start) / 86_400_000);
}

function band(c: FeedCall): string {
  const { amount_min: lo, amount_max: hi } = c;
  if (lo && hi) return lo === hi ? formatInr(hi) : `${formatInr(lo)} – ${formatInr(hi)}`;
  if (hi) return `Up to ${formatInr(hi)}`;
  if (lo) return `From ${formatInr(lo)}`;
  return "Amount not stated";
}

export function CallCard({
  call,
  canAct,
  orgName,
  busy,
  onStatus,
  onAsk,
}: {
  call: FeedCall;
  canAct: boolean;
  orgName: string;
  busy: boolean;
  onStatus: (status: "flagged" | "saved" | "dismissed") => void;
  onAsk: () => void;
}) {
  const days = daysLeft(call.deadline);
  const closed = call.call_status !== "open" || (days !== null && days < 0);
  const saved = call.status === "saved";
  // Extracted from a web page by a model, so only an http(s) link is rendered.
  const link = safeHref(call.url) ?? safeHref(call.source_url);

  return (
    <article className="rfp-card" data-closed={closed} aria-label={call.title}>
      <div className="rfp-card-top">
        <div className="rfp-card-name">
          <span className="rfp-funder">{call.funder_name ?? "Funder not recorded"}</span>
          <h3 className="rfp-title">{call.title}</h3>
        </div>
        <div className="rfp-due">
          {closed ? (
            <span className="tag tag-outline">Closed</span>
          ) : (
            <span className={days !== null && days <= URGENT_DAYS ? "tag tag-track" : "tag tag-neutral"}>
              <CalendarClock className="icon icon-sm" />
              {days === 0 ? "Due today" : `${days} day${days === 1 ? "" : "s"} left`}
            </span>
          )}
          {call.deadline && (
            <span className="rfp-due-date">
              {closed ? "Closed" : "Due"} {dayMonthYear(call.deadline)}
            </span>
          )}
        </div>
      </div>

      <div className="rfp-facts">
        <span>
          <IndianRupee className="icon icon-sm" />
          {band(call)}
        </span>
        <span>
          <MapPin className="icon icon-sm" />
          {call.places.length ? call.places.join(", ") : "Place not stated"}
        </span>
      </div>

      {call.themes.length > 0 && (
        <div className="rfp-themes">
          <span className="rfp-themes-label">Matches your theme</span>
          {call.themes.map((t) => (
            <span key={t} className="tag tag-accent-2">
              {t}
            </span>
          ))}
        </div>
      )}

      <div className="rfp-actions">
        {canAct ? (
          <>
            <button
              type="button"
              className={saved ? "btn rfp-saved" : "btn btn-primary"}
              aria-pressed={saved}
              disabled={busy}
              onClick={() => onStatus(saved ? "flagged" : "saved")}
            >
              <Bookmark className="icon icon-sm" data-filled={saved} />
              {saved ? "Saved" : "Save"}
            </button>
            <button type="button" className="btn rfp-dismiss" disabled={busy} onClick={() => onStatus("dismissed")}>
              <X className="icon icon-sm" />
              {saved && closed ? "Remove" : "Not for us"}
            </button>
          </>
        ) : (
          <span className="rfp-readonly">Only members and admins of {orgName} can save or hide calls.</span>
        )}
        <button type="button" className="btn btn-secondary" onClick={onAsk}>
          <MessageSquare className="icon icon-sm" />
          Ask about this call
        </button>
        {link && (
          <a className="rfp-link" href={link} target="_blank" rel="noreferrer">
            Read the call
            <ExternalLink className="icon icon-sm" />
          </a>
        )}
      </div>
    </article>
  );
}
