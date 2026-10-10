/* The fixed funder types (media spec D13); how CSR is spent shows after the " · ", the filter uses the part before. */
const LABEL: Record<string, string> = {
  corporate_csr: "Corporate CSR · run by the company",
  corporate_foundation: "Corporate CSR · through its foundation",
  csr_foundation: "Corporate CSR · through its foundation",
  private_foundation: "Private or family foundation",
  family_trust: "Private or family foundation",
  family_trust_network: "Private or family foundation",
};

export const funderTypeLabel = (type: string | null) => (type && LABEL[type]) || "Other";
export const funderTypeGroup = (type: string | null) => funderTypeLabel(type).split(" · ")[0];
