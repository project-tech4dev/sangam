"use client";

import { AgentProviders } from "@/lib/AgentProviders";
import { AskWorkspace, type IndexPayload } from "./AskWorkspace";

export function SignedInWorkspace({
  payload,
  initialQuestion,
}: {
  payload: IndexPayload;
  initialQuestion: string | null;
}) {
  return (
    <AgentProviders>
      <AskWorkspace payload={payload} initialQuestion={initialQuestion} />
    </AgentProviders>
  );
}
