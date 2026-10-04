"use client";

import { CopilotKitProvider } from "@copilotkit/react-core/v2";
import type { ReactNode } from "react";

export function AgentProviders({ children }: { children: ReactNode }) {
  return (
    <CopilotKitProvider
      runtimeUrl="/api/copilotkit"
      agentId="sangam_agent"
      useSingleEndpoint={false}
      // Auth stub: same wire shape as the future Supabase JWT.
      headers={{ Authorization: "Bearer dev" }}
    >
      {children}
    </CopilotKitProvider>
  );
}
