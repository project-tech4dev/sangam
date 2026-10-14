"use client";

import { useState } from "react";
import type { Proposal } from "./api";

const SEEN = "sangam.proposal.how-it-works";

/** "Your promises from Sangam", in the side panel on step 1 until dismissed, once per browser. */
export function HowItWorks({ proposal }: { proposal: Proposal }) {
  // Rendered only after the proposal loads in the browser, so reading storage here never meets the server render.
  const [show, setShow] = useState(() => {
    try {
      return window.localStorage.getItem(SEEN) !== "1";
    } catch {
      return true;
    }
  });

  function dismiss() {
    setShow(false);
    try {
      window.localStorage.setItem(SEEN, "1");
    } catch {}
  }

  if (!show) return null;
  return (
    <section className="card pr-side-card" aria-label="Your promises from Sangam">
      <div className="card-title">Your promises from Sangam</div>
      <ul className="pr-promises">
        <li>
          Sangam reads only what you allow: what it already knows about {proposal.org.name} and {proposal.funder.name}, and the
          files you tick.
        </li>
        <li>Every fact shows where it came from. A fact from the web is marked &ldquo;not checked&rdquo; until you confirm it.</li>
        <li>You decide. Sangam asks one question at a time, and nothing goes into the proposal until you say yes.</li>
        <li>Your numbers stay yours. Sangam never changes a number, a place or a name when it smooths the language.</li>
        <li>Nothing is sent for you. You download the finished proposal and send it yourself.</li>
      </ul>
      <button className="btn btn-ghost pr-back" type="button" onClick={dismiss}>
        Got it
      </button>
    </section>
  );
}
