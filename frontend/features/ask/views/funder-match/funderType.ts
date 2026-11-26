/* The fixed funder types (media spec D13); how CSR is spent shows after the " · ", the filter uses the part before. */
const LABEL: Record<string, string> = {
  csr_company: "Corporate CSR · run by the company",
  csr_foundation: "Corporate CSR · through its foundation",
  private_foundation: "Private or family foundation",
  hni: "Individual or giving network",
  intermediary: "Re-granting fund or intermediary",
  international_agency: "International development or church agency",
  bilateral_multilateral: "Bilateral or multilateral donor",
  government: "Government or statutory body",
};

export const funderTypeLabel = (type: string | null) => (type && LABEL[type]) || "Other";
export const funderTypeGroup = (type: string | null) => funderTypeLabel(type).split(" · ")[0];
