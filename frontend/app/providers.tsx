"use client";

import { CopilotKitProvider } from "@copilotkit/react-core/v2";
import type { ReactNode } from "react";
import { TooltipProvider } from "@/components/ui/tooltip";

export function Providers({ children }: { children: ReactNode }) {
  return (
    <CopilotKitProvider
      runtimeUrl="/api/copilotkit"
      agentId="sangam_agent"
      useSingleEndpoint={false}
      // Auth stub: same wire shape as the future Supabase JWT.
      headers={{ Authorization: "Bearer dev" }}
    >
      {/* Tooltip and Sidebar need one provider above them. */}
      <TooltipProvider>{children}</TooltipProvider>
    </CopilotKitProvider>
  );
}
