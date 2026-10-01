import type { ReactNode } from "react";
import { Providers } from "./providers";

// CopilotKit's client runtime pulls in AG-UI, zod, katex, mermaid and lit. Only
// /ask and /import talk to an agent, so the provider is scoped to this group
// rather than the root layout — /registry must not pay for it.
export default function AgentLayout({ children }: { children: ReactNode }) {
  return <Providers>{children}</Providers>;
}
