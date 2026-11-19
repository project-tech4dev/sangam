import type { FreeQuestions } from "@/lib/api";

/** How many of the free questions someone outside every organisation has used. */
export function FreeQuestionsLine({ used, limit }: FreeQuestions) {
  return <div className="muted composer-quota">{Math.min(used, limit)} of {limit} free questions used</div>;
}

/** In place of the question box once they are all used; past chats stay readable above it. */
export function FreeQuestionsSpent({ limit }: { limit: number }) {
  return (
    <div className="card elev-sm composer composer-spent" role="status">
      You&apos;ve used your {limit} free questions. You can&apos;t ask new questions.
    </div>
  );
}
