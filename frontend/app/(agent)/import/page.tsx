import { redirect } from "next/navigation";
import { ImportLoader } from "@/features/ingest/ImportLoader";
import { canUseScout, type Me } from "@/features/ingest/lib/access";
import { apiGet } from "@/lib/api";

export const metadata = { title: "Sangam Scout" };

export const dynamic = "force-dynamic";

// Signed out, the proxy sends a visitor to sign-in first (next=/import); signed in, Scout is for stewards
// and staff, and anyone else goes to Ask. ?thread= reopens a past import.
export default async function ImportRoute({ searchParams }: { searchParams: Promise<{ thread?: string }> }) {
  const me = await apiGet<Me>("/api/me").catch(() => null);
  if (!me || !canUseScout(me)) redirect("/ask");
  const { thread } = await searchParams;
  const initialThread = thread && /^import-[0-9a-f-]{36}$/.test(thread) ? thread : null;
  return (
    <div data-app-shell className="import-shell">
      <ImportLoader initialThread={initialThread} />
    </div>
  );
}
