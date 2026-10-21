"use client";

import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import remarkGfm from "remark-gfm";

/** The last search's brief, written from open web research: problem magnitude, impact evidence and caveats. */
export function ResearchBrief({ text }: { text: string }) {
  return (
    <section className="answer-md" aria-label="Research brief">
      {/* Written from pages on the open web: never raw HTML, never a javascript: link. */}
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        skipHtml
        urlTransform={defaultUrlTransform}
        components={{
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noopener noreferrer">
              {children}
            </a>
          ),
          table: (props) => (
            <div className="scout-reply-scroll">
              <table {...props} />
            </div>
          ),
        }}
      >
        {text}
      </ReactMarkdown>
    </section>
  );
}
