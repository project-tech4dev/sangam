"use client";

/* The list-page pattern: lean bucket cards, one row of dropdowns, a search box, a list that grows as you scroll. */
import { useEffect, useRef, useState } from "react";
import { Search } from "lucide-react";

export type Bucket<K extends string> = { key: K; label: string; count: number; sub?: string };

export function BucketCards<K extends string>({
  items,
  active,
  onPick,
  label = "Show",
}: {
  items: Bucket<K>[];
  active: K;
  onPick: (key: K) => void;
  label?: string;
}) {
  return (
    <div className="bucket-cards" role="group" aria-label={label}>
      {items.map((item) => (
        <button
          key={item.key}
          type="button"
          className="bucket-card"
          data-active={item.key === active}
          aria-pressed={item.key === active}
          onClick={() => onPick(item.key)}
        >
          <span className="bucket-card-top">
            <span className="bucket-card-num">{item.count}</span>
            <span className="bucket-card-label">{item.label}</span>
          </span>
          {item.sub && <span className="bucket-card-sub">{item.sub}</span>}
        </button>
      ))}
    </div>
  );
}

export type Filter = {
  key: string;
  label: string;
  value: string;
  defaultValue: string;
  options: [value: string, label: string][];
  onChange: (value: string) => void;
};

/* A dropdown off its default turns dark sage, so a changed filter is visible at a glance. */
export function FilterRow({ filters }: { filters: Filter[] }) {
  if (filters.length === 0) return null;
  return (
    <div className="filter-row">
      {filters.map((f) => (
        <select
          key={f.key}
          className="filter"
          aria-label={f.label}
          value={f.value}
          data-set={f.value !== f.defaultValue}
          onChange={(event) => f.onChange(event.target.value)}
        >
          {f.options.map(([value, text]) => (
            <option key={value} value={value}>
              {text}
            </option>
          ))}
        </select>
      ))}
    </div>
  );
}

export function SearchBox({
  value,
  onChange,
  placeholder,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
}) {
  return (
    <label className="search-box">
      <Search className="icon icon-sm" />
      <input type="search" value={value} placeholder={placeholder} aria-label={placeholder} onChange={(e) => onChange(e.target.value)} />
    </label>
  );
}

/* How many rows to show; back to one page whenever `resetKey` changes (a filter, the search, the bucket). */
export function useShowMore(resetKey: string, page = 10): [number, () => void] {
  const [shown, setShown] = useState({ key: resetKey, n: page });
  const n = shown.key === resetKey ? shown.n : page;
  return [n, () => setShown({ key: resetKey, n: n + page })];
}

/* The foot of a growing list: loads the next page near the end, but only once the person has scrolled. */
export function ListMore({
  shown,
  total,
  onMore,
  page = 10,
  busy = false,
}: {
  shown: number;
  total: number;
  onMore: () => void;
  page?: number;
  busy?: boolean;
}) {
  const button = useRef<HTMLButtonElement>(null);
  const more = useRef(onMore);
  const left = total - shown;

  useEffect(() => {
    more.current = onMore;
  });

  useEffect(() => {
    const el = button.current;
    if (!el || left <= 0 || busy) return;
    let scrolled = false;
    const onScroll = () => (scrolled = true);
    document.addEventListener("scroll", onScroll, { capture: true, passive: true });
    const io = new IntersectionObserver(
      (entries) => {
        if (scrolled && entries.some((entry) => entry.isIntersecting)) more.current();
      },
      { rootMargin: "150px" },
    );
    io.observe(el);
    return () => {
      io.disconnect();
      document.removeEventListener("scroll", onScroll, { capture: true });
    };
  }, [left, busy]);

  if (total === 0) return null;
  if (left <= 0) return <p className="muted list-end">End of the list</p>;
  return (
    <button ref={button} type="button" className="btn btn-ghost list-more" onClick={onMore} disabled={busy}>
      {busy ? "Loading…" : `Show ${Math.min(page, left)} more · ${left} left`}
    </button>
  );
}
