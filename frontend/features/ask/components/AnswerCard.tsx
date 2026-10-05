"use client";

import Link from "next/link";
import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import remarkGfm from "remark-gfm";
import { citationTarget, linkifyCitations, type CitationKind, type RegistryIndex } from "../lib/citations";

export function CitationChip({ href: raw, index }: { href: string; index: RegistryIndex | null }) {
  const [, kind, id] = raw.match(/^sangam:\/\/([a-z]+)\/(.+)$/) ?? [];
  if (!kind || !id) return null;
  const { href, label } = citationTarget(kind as CitationKind, id, index);
  // The marker the agent emitted is what the chip shows. The model has just written the
  // entity's name in the prose beside it, so repeating the name here would say it twice —
  // and in a table it would widen the column. The name goes in the title instead.
  const marker = `${kind}:${id}`;
  const chipStyle = {
    display: "inline-flex",
    alignItems: "center",
    fontSize: "var(--fs-xs)",
    fontWeight: 600,
    padding: "1px 8px",
    borderRadius: 999,
    background: "var(--color-accent-100)",
    color: "var(--color-accent-800)",
    textDecoration: "none",
    verticalAlign: "text-bottom",
    margin: "0 1px",
  } as const;
  if (!href) {
    return (
      <span style={chipStyle} title={`${label} — ${kind} evidence in the base`}>
        {marker}
      </span>
    );
  }
  return (
    <Link href={href} style={chipStyle} title={`Open ${label} in the Registry`}>
      {marker}
    </Link>
  );
}

export function AnswerCard({ answer, index }: { answer: string; index: RegistryIndex | null }) {
  return (
    <div className="ask-in" style={{ display: "flex", gap: 12 }}>
      <div
        aria-hidden
        style={{
          width: 34,
          height: 34,
          borderRadius: "50%",
          flexShrink: 0,
          background: "var(--color-accent-750)",
          color: "#fff",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontFamily: "var(--font-heading)",
          fontWeight: 700,
          fontSize: "var(--fs-sm)",
        }}
      >
        S
      </div>
      <div className="answer-md" style={{ fontSize: "var(--fs-sm)", lineHeight: 1.6, minWidth: 0, flex: 1 }}>
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          // react-markdown sanitises every scheme outside /^(https?|ircs?|mailto|xmpp)$/,
          // rewriting `sangam://funder/22` to "". That silently defeated the check below,
          // so every citation rendered as a dead <a> showing its raw marker and no chip
          // ever appeared. Let our own scheme through; everything else keeps the default.
          urlTransform={(url) => (url.startsWith("sangam://") ? url : defaultUrlTransform(url))}
          components={{
            a: ({ href, children }) =>
              href?.startsWith("sangam://") ? (
                <CitationChip href={href} index={index} />
              ) : (
                <a href={href} target="_blank" rel="noreferrer">
                  {children}
                </a>
              ),
            table: (props) => (
              <div style={{ overflowX: "auto" }}>
                <table {...props} />
              </div>
            ),
          }}
        >
          {linkifyCitations(answer)}
        </ReactMarkdown>
      </div>
    </div>
  );
}
