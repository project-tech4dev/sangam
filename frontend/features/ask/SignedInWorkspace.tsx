"use client";

import { AgentProviders } from "@/lib/AgentProviders";
import { AskWorkspace, type IndexPayload } from "./AskWorkspace";
import type { WorkspaceView } from "./components/Sidebar";

export function SignedInWorkspace({
  payload,
  initialQuestion,
  initialView,
}: {
  payload: IndexPayload;
  initialQuestion: string | null;
  initialView?: WorkspaceView;
}) {
  return (
    <AgentProviders>
      <AskWorkspace payload={payload} initialQuestion={initialQuestion} initialView={initialView} />
    </AgentProviders>
  );
}
