"use client";

import { CopilotKit } from "@copilotkit/react-core";
import type { ReactNode } from "react";

export function Providers({ children }: { children: ReactNode }) {
  return (
    <CopilotKit
      runtimeUrl="/api/copilotkit"
      agent="sangam_agent"
      useSingleEndpoint={false}
      // Auth stub: same wire shape as the future Supabase JWT.
      headers={{ Authorization: "Bearer dev" }}
    >
      {children}
    </CopilotKit>
  );
}
