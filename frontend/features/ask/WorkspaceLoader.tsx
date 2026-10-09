"use client";

import dynamic from "next/dynamic";
import type { IndexPayload } from "./AskWorkspace";

// /ask serves both the signed-out preview and the workspace. Anything the page imports
// statically lands in its client bundle, so the workspace — and the CopilotKit runtime
// under it — sits behind this lazy boundary and downloads only when it renders.
const SignedInWorkspace = dynamic(() => import("./SignedInWorkspace").then((m) => m.SignedInWorkspace), {
  loading: () => (
    <div className="muted" style={{ padding: 24 }}>
      Opening your workspace…
    </div>
  ),
});

export function WorkspaceLoader({
  payload,
  initialQuestion,
}: {
  payload: IndexPayload;
  initialQuestion: string | null;
}) {
  return <SignedInWorkspace payload={payload} initialQuestion={initialQuestion} />;
}
