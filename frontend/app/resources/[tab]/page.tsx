import { notFound } from "next/navigation";
import { MethodologyArticle } from "@/features/resources/MethodologyArticle";
import { ResourcesShell } from "@/features/resources/ResourcesShell";
import { TaxonomyArticle } from "@/features/resources/TaxonomyArticle";
import { TABS, isTabId } from "@/features/resources/tabs";

export const generateStaticParams = () => TABS.map((t) => ({ tab: t.id }));
export const dynamicParams = false;

export async function generateMetadata({ params }: { params: Promise<{ tab: string }> }) {
  const { tab } = await params;
  const label = TABS.find((t) => t.id === tab)?.label;
  return { title: label ? `${label} — Resources — Sangam` : "Resources — Sangam" };
}

export default async function ResourcesTab({ params }: { params: Promise<{ tab: string }> }) {
  const { tab } = await params;
  if (!isTabId(tab)) notFound();
  return (
    <ResourcesShell tab={tab}>{tab === "methodology" ? <MethodologyArticle /> : <TaxonomyArticle />}</ResourcesShell>
  );
}
