/* Which workspace screen an /ask address names. Pure, so it is tested without a browser. */

export const WORKSPACE_VIEWS = ["ask", "chats", "funder-match", "proposals", "rfpwatch", "vault", "media"] as const;
export type WorkspaceView = (typeof WORKSPACE_VIEWS)[number];

/** `?view=`, or the chat when it is missing or unknown. */
export function viewFrom(value: string | null): WorkspaceView {
  return (WORKSPACE_VIEWS as readonly string[]).includes(value ?? "") ? (value as WorkspaceView) : "ask";
}

/** The params a sidebar pick writes: the chat is the bare URL, and another screen's ids do not follow you. */
export function viewParams(view: WorkspaceView): Record<string, string | null> {
  return { view: view === "ask" ? null : view, proposal: null, funder: null, org: null };
}
