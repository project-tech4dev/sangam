import { ImportLoader } from "@/features/ingest/ImportLoader";

export const metadata = { title: "Sangam Scout" };

export const dynamic = "force-dynamic";

// Signed out, the proxy sends a visitor to sign-in first (next=/import). ?thread= reopens a past import.
export default async function ImportRoute({ searchParams }: { searchParams: Promise<{ thread?: string }> }) {
  const { thread } = await searchParams;
  const initialThread = thread && /^import-[0-9a-f-]{36}$/.test(thread) ? thread : null;
  return (
    <div data-app-shell className="import-shell">
      <ImportLoader initialThread={initialThread} />
    </div>
  );
}
