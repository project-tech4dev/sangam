import { SectionIndex } from "@/components/ui/SectionIndex";
import { SECTIONS } from "./sections";

const ENTRIES = SECTIONS.map(([id, label]) => ({ id, label }));

export function TermsIndex() {
  return <SectionIndex sections={ENTRIES} />;
}
