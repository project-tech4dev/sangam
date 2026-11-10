/* Screens live in the address so Back, reload and a shared link all land on them. */

export type ParamPatch = Record<string, string | null | undefined>;

/** `href` with `patch` applied: a null, undefined or empty value drops the param. Pure. */
export function withParams(href: string, patch: ParamPatch): string {
  const url = new URL(href);
  for (const [key, value] of Object.entries(patch)) {
    if (value === null || value === undefined || value === "") url.searchParams.delete(key);
    else url.searchParams.set(key, value);
  }
  return url.href;
}

/** A screen change is a push (Back undoes it); a filter or a fill-in is a replace (Back skips it). */
export function setUrlParams(patch: ParamPatch, mode: "push" | "replace" = "push") {
  const next = withParams(window.location.href, patch);
  if (next === window.location.href) return;
  if (mode === "push") window.history.pushState(null, "", next);
  else window.history.replaceState(null, "", next);
}

/** A positive integer param, or null. */
export function idParam(value: string | null): number | null {
  const n = Number(value);
  return value && Number.isInteger(n) && n > 0 ? n : null;
}

/** `value` when it names one of `ids`, else the first. */
export function oneOf<T extends string>(value: string | null, ids: readonly T[]): T {
  return ids.includes(value as T) ? (value as T) : ids[0]!;
}
