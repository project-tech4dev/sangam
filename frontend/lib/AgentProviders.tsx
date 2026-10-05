"use client";

import { CopilotKitProvider } from "@copilotkit/react-core/v2";
import { useEffect, useState, type ReactNode } from "react";
import { createClient } from "@/lib/supabase/client";

export function AgentProviders({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(null);

  useEffect(() => {
    const supabase = createClient();
    supabase.auth.getSession().then(({ data }) => setToken(data.session?.access_token ?? null));
    const { data } = supabase.auth.onAuthStateChange((_event, session) => {
      setToken(session?.access_token ?? null);
    });
    return () => data.subscription.unsubscribe();
  }, []);

  return (
    <CopilotKitProvider
      runtimeUrl="/api/copilotkit"
      agentId="sangam_agent"
      useSingleEndpoint={false}
      headers={token ? { Authorization: `Bearer ${token}` } : {}}
    >
      {children}
    </CopilotKitProvider>
  );
}
