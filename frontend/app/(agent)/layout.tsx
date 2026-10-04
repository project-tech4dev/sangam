import type { ReactNode } from "react";

// CopilotKit's client runtime pulls in AG-UI, zod, katex, mermaid and lit, so it must
// load only where an agent runs. That is not the whole group any more: signed out,
// /ask is a static preview. Each page wraps its agent UI in <AgentProviders> (lib/AgentProviders.tsx).
export default function AgentLayout({ children }: { children: ReactNode }) {
  return children;
}
