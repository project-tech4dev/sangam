/* Display formatting shared across screens. */

/** Source data arrives SHOUTING from the Darpan portal; mixed case is left alone. */
export function titleCase(value: string | null): string {
  if (!value) return "";
  if (value !== value.toUpperCase()) return value; // already mixed case — leave as-is
  return value
    .toLowerCase()
    .split(/\s+/)
    .map((w) => (w.length > 2 ? w[0]!.toUpperCase() + w.slice(1) : w.toUpperCase()))
    .join(" ");
}

/** Rupees as staff say them: ₹4.2 crore, ₹75 lakh, ₹40,000. */
export function formatInr(value: number): string {
  const abs = Math.abs(value);
  const sign = value < 0 ? "-" : "";
  const short = (n: number) => n.toLocaleString("en-IN", { maximumFractionDigits: n < 10 ? 2 : 1 });
  if (abs >= 1e7) return `${sign}₹${short(abs / 1e7)} crore`;
  if (abs >= 1e5) return `${sign}₹${short(abs / 1e5)} lakh`;
  return `${sign}₹${abs.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

/** "10 Oct 2026", the date style of Funder Match and Proposals. */
export const shortDate = (iso: string) =>
  new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });

/** A name as the Registry shows it: one capitalised word is an acronym (KABIL), several are Darpan shouting. */
export function displayName(name: string): string {
  return /\s/.test(name.trim()) ? titleCase(name) : name;
}

export const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
  "October", "November", "December"];
const SHORT_MONTHS = MONTHS.map((m) => m.slice(0, 3));

/** "12 Oct 2026", or "Oct 2026" / "2026" when the ISO date is only that precise. Read as text: no timezone slip. */
export function dayMonthYear(iso: string | null | undefined): string {
  if (!iso) return "";
  const [y, m, d] = iso.slice(0, 10).split("-");
  return [d && String(Number(d)), m && SHORT_MONTHS[Number(m) - 1], y].filter(Boolean).join(" ");
}

/** "Oct 2026", or "October 2026" with `long`. */
export function monthYear(iso: string | null | undefined, long = false): string | null {
  if (!iso) return null;
  const [y, m] = iso.slice(0, 10).split("-");
  return m ? `${(long ? MONTHS : SHORT_MONTHS)[Number(m) - 1]} ${y}` : y;
}

/** "12 Oct". */
export const dayMonth = (iso: string) => `${Number(iso.slice(8, 10))} ${SHORT_MONTHS[Number(iso.slice(5, 7)) - 1]}`;

const FUNDER_TYPES: Record<string, string> = {
  corporate_csr: "Corporate CSR", corporate_foundation: "Corporate foundation",
  private_foundation: "Private foundation", family_trust_network: "Family trust",
  international: "International", bilateral: "Bilateral", multilateral: "Multilateral",
  government: "Government", foundation: "Foundation",
};

/** A funder_type as a person reads it, the same on the Registry list and the profile. */
export function funderTypeLabel(type: string | null | undefined): string {
  if (!type) return "Funder";
  return FUNDER_TYPES[type] ?? type.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
}
