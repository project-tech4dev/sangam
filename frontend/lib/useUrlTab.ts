"use client";

import { useSearchParams } from "next/navigation";
import { oneOf, setUrlParams } from "./url";

/** A tab in `?tab=`: a pick is a Back step, and the first tab is the bare URL. */
export function useUrlTab(ids: readonly string[]): [string, (id: string) => void] {
  const tab = oneOf(useSearchParams().get("tab"), ids);
  return [tab, (id) => setUrlParams({ tab: id === ids[0] ? null : id })];
}
