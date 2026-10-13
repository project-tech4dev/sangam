import type { Story, StoryCounts } from "@/lib/api";
import { initialsOf } from "@/components/ui";
import { dayMonthYear, MONTHS } from "@/lib/format";
import { safeHref, SourceLink } from "./shared";

const PLATFORM_MARK: Record<string, string> = { LinkedIn: "Li", Instagram: "Ig", X: "X", YouTube: "Yt" };

/* Posts per month over the six months up to the latest post. */
function monthBars(posts: Story[]) {
  const dated = posts.map((p) => p.published_on).filter((d): d is string => !!d).sort();
  const last = dated.at(-1);
  if (!last) return [];
  let y = Number(last.slice(0, 4));
  let m = Number(last.slice(5, 7)) - 1;
  const months: { y: number; m: number }[] = [];
  for (let i = 0; i < 6; i++) {
    months.unshift({ y, m });
    m -= 1;
    if (m < 0) { m = 11; y -= 1; }
  }
  return months.map(({ y: yy, m: mm }) => ({
    y: yy, m: mm,
    n: dated.filter((d) => Number(d.slice(0, 4)) === yy && Number(d.slice(5, 7)) - 1 === mm).length,
  }));
}

/* The stories listed are the latest few; the headers count every public one, from SQL. */
export function NewsSocial({ stories, counts, name }: { stories: Story[]; counts: StoryCounts; name: string }) {
  const press = stories.filter((s) => s.channel === "press");
  const social = stories.filter((s) => s.channel === "social");
  const byPlatform = new Map<string, Story[]>();
  for (const s of social) {
    const k = s.source_type ?? s.main_host ?? "Social";
    byPlatform.set(k, [...(byPlatform.get(k) ?? []), s]);
  }
  const bars = monthBars(social);
  const max = Math.max(1, ...bars.map((b) => b.n));
  const barsLabel = bars.length
    ? `Posts found per month, ${MONTHS[bars[0].m]} to ${MONTHS[bars.at(-1)!.m]} ${bars.at(-1)!.y}: ${bars.map((b) => b.n).join(", ")}`
    : "";

  return (
    <div className="profile-news">
      <section className="profile-news-col">
        <h3>In the news · {counts.press}</h3>
        {counts.press === 0 && (
          <div className="profile-news-item">
            <div className="profile-av" data-empty="true">Pr</div>
            <div className="profile-news-body">
              <strong className="profile-body">No press coverage found</strong>
              <span className="muted profile-sm">
                {counts.social > 0
                  ? `Everything the news pulls found for ${name} was its own social posts.`
                  : `No stories about ${name} clear the public bar yet.`}
              </span>
            </div>
          </div>
        )}
        {press.map((n) => {
          const href = safeHref(n.main_url);
          return (
            <div key={n.row_id} className="profile-news-item">
              <div className="profile-av">{initialsOf(n.source_type ?? n.main_host ?? "News")}</div>
              <div className="profile-news-body">
                {href ? (
                  <a href={href} target="_blank" rel="noopener noreferrer" className="profile-strong profile-body">{n.headline} ↗</a>
                ) : <strong className="profile-body">{n.headline}</strong>}
                {n.summary && <span className="muted profile-sm">{n.summary}</span>}
                <span className="muted profile-sm">
                  {[n.main_host, n.source_type, dayMonthYear(n.published_on)].filter(Boolean).join(" · ")}
                </span>
                {n.also.length > 0 && (
                  <div className="profile-row">
                    <span className="muted profile-sm">Also reported by</span>
                    {n.also.map((a) => <SourceLink key={a.url} url={a.url} label={a.host} />)}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </section>

      <section className="profile-news-col">
        <h3>Social activity · {counts.social}</h3>
        {bars.length > 0 && (
          <>
            <div className="profile-bars" role="img" aria-label={barsLabel}>
              {bars.map((b) => (
                // The height is the month's share of the busiest month: a runtime value.
                <div key={`${b.y}-${b.m}`} className="profile-bar" data-on={b.n > 0} title={`${MONTHS[b.m].slice(0, 3)}: ${b.n}`}
                  style={{ height: `${Math.max(8, Math.round((b.n / max) * 100))}%` }} />
              ))}
            </div>
            <div className="muted profile-sm">{barsLabel}</div>
          </>
        )}
        {counts.social === 0 && (
          <div className="profile-news-item">
            <div className="profile-av" data-empty="true">Li</div>
            <div className="profile-news-body">
              <strong className="profile-body">No posts tracked yet</strong>
              <span className="muted profile-sm">News pulls have found no social posts by {name}.</span>
            </div>
          </div>
        )}
        {[...byPlatform.entries()].map(([platform, posts]) => (
          <div key={platform} className="profile-news-item">
            <div className="profile-av">{PLATFORM_MARK[platform] ?? initialsOf(platform)}</div>
            <div className="profile-news-body">
              <div className="profile-row">
                <strong className="profile-body">{platform}</strong>
                <span className="muted profile-sm">{posts.length} {posts.length === 1 ? "post" : "posts"}</span>
              </div>
              {posts.map((p) => {
                const href = safeHref(p.main_url);
                const body = (
                  <>
                    <span className="profile-sm profile-strong">{p.headline}</span>
                    {p.summary && <span className="muted profile-sm">{p.summary}</span>}
                    <span className="muted profile-sm">{dayMonthYear(p.published_on)}{href ? " · open post ↗" : ""}</span>
                  </>
                );
                return href ? (
                  <a key={p.row_id} className="profile-post" href={href} target="_blank" rel="noopener noreferrer">{body}</a>
                ) : <div key={p.row_id} className="profile-post">{body}</div>;
              })}
            </div>
          </div>
        ))}
      </section>
    </div>
  );
}
