import Link from "next/link";
import { notFound } from "next/navigation";
import { Breadcrumbs, Hero, Tag } from "@/components/ui";
import {
  apiGet, NotFoundError, type StoryPage,
  type FunderDetail, type PageOf, type PartnerLineRow, type ScoreRow,
} from "@/lib/api";
import { FunderProfileTabs } from "@/features/registry/ProfileTabs";

export default async function FunderProfilePage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  // Every sub-route takes a slug or an id, so all five calls start together.
  const detail = apiGet<FunderDetail>(`/api/funders/${slug}`);
  const rest = Promise.all([
    apiGet<PageOf<ScoreRow>>(`/api/scores?funder=${slug}&limit=50`).then((p) => p.items),
    apiGet<PageOf<PartnerLineRow>>(`/api/partner-lines?funder=${slug}&limit=50`),
    // News is one tab: a failed fetch leaves it empty rather than failing the profile.
    apiGet<StoryPage>(`/api/funders/${slug}/news?limit=50`).then((p) => p.items, () => []),
    // 404 when this funder has not been researched, which is most of them.
    // A signed link, so it is minted per render rather than stored.
    apiGet<{ url: string }>(`/api/funders/${slug}/brief`).catch(() => null),
  ]);
  rest.catch(() => {}); // a 404 below must not leave this rejection unhandled
  let funder: FunderDetail;
  try {
    funder = await detail;
  } catch (err) {
    if (err instanceof NotFoundError) notFound();
    throw err;
  }
  const [scores, partners, news, brief] = await rest;

  return (
    <div className="page" style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <Breadcrumbs
        items={[
          { label: "Sangam", href: "/registry" },
          { label: "Registry", href: "/registry" },
          { label: "Funders", href: "/registry?type=funder" },
          { label: funder.name },
        ]}
      />
      <Hero
        kind="funder"
        kicker="Funder profile"
        name={funder.name}
        blurb={(funder.profile?.funding_trend as string) ?? null}
        chips={
          <>
            {funder.funder_type && <Tag tone="ondark">{funder.funder_type.replace(/_/g, " ")}</Tag>}
            {funder.section_135_bound != null && (
              <Tag tone="ondark">{funder.section_135_bound ? "Section 135 bound" : "Not Section-135 bound"}</Tag>
            )}
            {funder.website && <Tag tone="ondark">{funder.website.replace(/^https?:\/\/(www\.)?/, "")}</Tag>}
          </>
        }
        cta={
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            <Link
              href={`/ask?q=${encodeURIComponent(`Which NGOs in the base fit ${funder.name}'s mandate, and why?`)}`}
              className="btn" style={{ background: "rgba(255,255,255,0.16)", color: "#fff" }}>
              Ask Sangam who fits this mandate →
            </Link>
            {brief && (
              <a
                href={brief.url}
                target="_blank"
                rel="noreferrer"
                className="btn"
                style={{ background: "rgba(255,255,255,0.16)", color: "#fff" }}
              >
                Research brief ↗
              </a>
            )}
          </div>
        }
      />
      <FunderProfileTabs
        funder={funder} scores={scores} partners={partners.items} partnersTotal={partners.total} news={news}
      />
    </div>
  );
}
