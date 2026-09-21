"use client";

import { useCopilotAction } from "@copilotkit/react-core";
import { CopilotChat } from "@copilotkit/react-ui";

// Catch-all renderer: shows every agent tool call (name, args, result) inline
// in the chat — the visible proof that answers come from Postgres, not priors.
function ToolCallRenderer() {
  useCopilotAction({
    name: "*",
    render: ({ name, args, result, status }) => (
      <details className="tool-call" open={status !== "complete"}>
        <summary>
          {status === "complete" ? "✓" : "…"} tool: <b>{name}</b>
        </summary>
        <pre>{JSON.stringify(args, null, 2)}</pre>
        {result != null && <pre>{typeof result === "string" ? result : JSON.stringify(result, null, 2)}</pre>}
      </details>
    ),
  });
  return null;
}

export default function Home() {
  return (
    <div className="chat-shell">
      <ToolCallRenderer />
      <CopilotChat
        labels={{
          title: "Ask Sangam",
          initial:
            "Ask me about the cohort's organisations, funders, or funder-fit scores — e.g. “Which NGOs in our database work in Assam?” or “How well does KABIL fit Axis Bank Foundation?”",
        }}
      />
    </div>
  );
}
