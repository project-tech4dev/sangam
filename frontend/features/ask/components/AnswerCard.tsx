"use client";

import Link from "next/link";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { citationTarget, linkifyCitations, type CitationKind, type RegistryIndex } from "../lib/citations";

export function CitationChip({ href: raw, index }: { href: string; index: RegistryIndex | null }) {
  const [, kind, id] = raw.match(/^sangam:\/\/([a-z]+)\/(.+)$/) ?? [];
  if (!kind || !id) return null;
  const { href, label } = citationTarget(kind as CitationKind, id, index);
  const chipStyle = {
    display: "inline-flex",
    alignItems: "center",
    fontSize: 10.5,
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
      <span style={chipStyle} title={`${kind} evidence in the base`}>
        {label}
      </span>
    );
  }
  return (
    <Link href={href} style={chipStyle} title={`Open ${label} in the Registry`}>
      {label}
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
          background: "var(--color-accent-600)",
          color: "#fff",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontFamily: "var(--font-heading)",
          fontWeight: 700,
          fontSize: 14,
        }}
      >
        S
      </div>
      <div className="answer-md" style={{ fontSize: 14, lineHeight: 1.6, minWidth: 0, flex: 1 }}>
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
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
