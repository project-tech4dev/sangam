"use client";

/* A use case listed in the sidebar that has not shipped yet. */
export function ComingSoonView({ title, body }: { title: string; body: string }) {
  return (
    <div className="view">
      <div>
        <div className="eyebrow">Use Cases</div>
        <h2 className="view-title">{title}</h2>
      </div>
      <div className="card view-measure soon-card">
        <span className="tag tag-outline">Coming soon</span>
        <div className="card-body">{body}</div>
      </div>
    </div>
  );
}
