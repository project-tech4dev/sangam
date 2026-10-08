import Link from "next/link";
import { notFound } from "next/navigation";
import { Breadcrumbs, Hero, Tag } from "@/components/ui";
import {
  apiGet, NotFoundError,
  type GrantRow, type NewsRow, type OrgDetail, type PageOf, type ProgramRow, type ScoreRow,
} from "@/lib/api";
import { titleCase } from "@/lib/format";
import { isOnFile, pickIdentifier, statusLabel } from "@/features/registry/identifierStatus";
import { OrgProfileTabs } from "@/features/registry/ProfileTabs";

export default async function OrgProfilePage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  let org: OrgDetail;
  try {
    org = await apiGet<OrgDetail>(`/api/orgs/${slug}`);
  } catch (err) {
    if (err instanceof NotFoundError) notFound();
    throw err;
  }

  const [grants, programs, scores, news] = await Promise.all([
    apiGet<PageOf<GrantRow>>(`/api/grants?org=${org.slug}&limit=50`).then((p) => p.items),
    apiGet<PageOf<ProgramRow>>(`/api/programs?org=${org.slug}&limit=50`).then((p) => p.items),
    apiGet<PageOf<ScoreRow>>(`/api/scores?org=${org.slug}&limit=50`).then((p) => p.items),
    apiGet<PageOf<NewsRow>>(`/api/news?org=${org.slug}&limit=10`).then((p) => p.items),
  ]);

  const isFull = org.identifiers.filter((i) => isOnFile(i)).length >= 4;
  const displayName = titleCase(org.name);

  return (
    <div className="page" style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <Breadcrumbs
        items={[
          { label: "Sangam", href: "/registry" },
          { label: "Registry", href: "/registry" },
          { label: org.state ?? "India" },
          { label: displayName },
        ]}
      />
      <Hero
        kind={isFull ? "org-full" : "org-partial"}
        kicker={org.legal_form ?? "Civil-society organisation"}
        name={displayName}
        blurb={
          org.registration_date
            ? `Registered ${new Date(org.registration_date).toLocaleDateString("en-IN", { year: "numeric", month: "long" })}${org.district ? ` · ${titleCase(org.district)}, ${org.state}` : ""}`
            : null
        }
        chips={
          <>
            <Tag tone="ondark">{isFull ? "Base coverage — good" : "Base coverage — partial"}</Tag>
            {["fcra", "80g", "12a", "csr1"].map((idType) => {
              const found = pickIdentifier(org.identifiers, idType);
              return (
                <Tag key={idType} tone="ondark">
                  {`${idType.toUpperCase()} — ${statusLabel(found).toLowerCase()}`}
                </Tag>
              );
            })}
          </>
        }
        cta={
          <Link
            href={`/ask?q=${encodeURIComponent(`What does ${displayName} do, where does it work, and which funders fit it?`)}`}
            className="btn" style={{ background: "rgba(255,255,255,0.16)", color: "#fff" }}>
            Ask Sangam about this CSO →
          </Link>
        }
      />
      <OrgProfileTabs org={org} grants={grants} programs={programs} scores={scores} news={news} />
    </div>
  );
}
