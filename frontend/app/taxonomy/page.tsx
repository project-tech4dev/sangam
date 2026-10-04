import { redirect } from "next/navigation";

// Taxonomy is a tab of Resources now; its old ?domain= tabs are sections, so keep the deep link.
export default async function Taxonomy({ searchParams }: { searchParams: Promise<{ domain?: string }> }) {
  const { domain } = await searchParams;
  const anchor = domain === "shared" ? "shared-vocabulary" : domain && /^[a-z]+$/.test(domain) ? domain : null;
  redirect(`/resources/taxonomy${anchor ? `#${anchor}` : ""}`);
}
