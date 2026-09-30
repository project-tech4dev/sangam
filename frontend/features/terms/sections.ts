
export const SECTIONS = [
  ["t-about", "About these terms"],
  ["t-access", "Public and signed-in areas"],
  ["t-registry", "The public Registry"],
  ["t-vaults", "Organisation vaults"],
  ["t-ai", "How Sangam uses AI"],
  ["t-vendors", "Third-party AI providers"],
  ["t-collect", "What we collect"],
  ["t-use", "How we use it"],
  ["t-retention", "Retention and deletion"],
  ["t-rights", "Your rights"],
  ["t-acceptable", "Acceptable use"],
  ["t-liability", "Disclaimers"],
  ["t-contact", "Changes and contact"],
] as const;

export type SectionId = (typeof SECTIONS)[number][0];
