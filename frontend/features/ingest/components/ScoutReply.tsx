"use client";

import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import remarkGfm from "remark-gfm";

/** Scout's side of the conversation: its written reply, as a chat message. */
export function ScoutReply({ text }: { text: string }) {
  return (
    <div className="scout-reply">
      <span className="scout-reply-mark" aria-hidden>
        S
      </span>
      <div className="scout-reply-body answer-md">
        {/* The text is the agent's, written from pages on the open web: never raw HTML, never a javascript: link. */}
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
      </div>
    </div>
  );
}
