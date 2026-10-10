"use client";

import dynamic from "next/dynamic";

// The CopilotKit runtime under Import downloads only when the page renders. Browser-only: it reads the screen width.
const ImportPage = dynamic(() => import("./ImportPage").then((m) => m.ImportPage), {
  ssr: false,
  loading: () => <div className="muted import-loading">Opening Scout…</div>,
});

export function ImportLoader({ initialThread }: { initialThread: string | null }) {
  return <ImportPage initialThread={initialThread} />;
}
