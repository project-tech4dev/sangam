"use client";

import Link from "next/link";
import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import remarkGfm from "remark-gfm";
import { citationTarget, linkifyCitations, type CitationKind, type RegistryIndex } from "../lib/citations";

/** A source in words instead of its marker, for screens that show no codes (Sangam Pitch). */
export type SourceWords = Partial<Record<CitationKind, string>>;

export function CitationChip({ href: raw, index, words }: { href: string; index: RegistryIndex | null; words?: SourceWords }) {
  const [, kind, id] = raw.match(/^sangam:\/\/([a-z]+)\/(.+)$/) ?? [];
  if (!kind || !id) return null;
  const { href, label } = citationTarget(kind as CitationKind, id, index);
  // The marker the agent emitted is what the chip shows: the model has just written the entity's name beside it.
  const text = words?.[kind as CitationKind] ?? `${kind}:${id}`;
  if (!href) {
    return (
      <span className="cite-chip" title={`${label} — ${kind} evidence in the base`}>
        {text}
      </span>
    );
  }
  return (
    <Link href={href} className="cite-chip" title={`Open ${label} in the Registry`}>
      {text}
    </Link>
  );
}

export function AnswerCard({ answer, index, words }: { answer: string; index: RegistryIndex | null; words?: SourceWords }) {
  return (
    <div className="ask-in answer-row">
      <div aria-hidden className="answer-avatar">
        S
      </div>
      <div className="answer-md answer-body">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          // react-markdown sanitises every scheme outside /^(https?|ircs?|mailto|xmpp)$/,
          // rewriting `sangam://funder/22` to "". Let our own scheme through; everything else keeps the default.
          urlTransform={(url) => (url.startsWith("sangam://") ? url : defaultUrlTransform(url))}
          components={{
            a: ({ href, children }) =>
              href?.startsWith("sangam://") ? (
                <CitationChip href={href} index={index} words={words} />
              ) : (
                <a href={href} target="_blank" rel="noreferrer">
                  {children}
                </a>
              ),
            table: (props) => (
              <div className="answer-table-wrap">
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
