import Image from "next/image";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { HeroSlides } from "./HeroSlides";

// The home screen from the prototype handoff (Sangam Prototype.html#home).
// Colours are the handoff tokens in app/globals.css: terracotta = accent, sage = accent-2,
// sand = neutral. Everything renders inside .sangam-ui, the only place those tokens apply.

const STEPS = [
  {
    title: "You ask Sangam",
    body: "A question on funder fit, narrative strength, or proposal readiness.",
  },
  {
    title: "Reads the question",
    body: "Identifies who is asking and what kind of match is being requested.",
  },
  {
    title: "Pulls the material",
    body: "Retrieves the relevant funder mandates, NGO profiles, and media signal.",
  },
  {
    title: "Scores against the rubric",
    body: "A shared rubric produces the fit score.",
  },
  {
    title: "Returns an answer",
    body: "A direct answer with sources, confidence, and the steps it took attached.",
  },
] as const;

const SOURCES = [
  {
    kicker: "Funder side",
    title: "Funder priorities & CSR filings",
    body: "MCA CSR portal, BRSR filings, and CSR-1 registry entries.",
  },
  {
    kicker: "NGO side",
    title: "NGO profiles",
    body: "NGO Darpan records and direct profiles from the organisations themselves.",
  },
  {
    kicker: "Signal",
    title: "Media — news & social signal",
    body: "Executive LinkedIn posts, founder updates, and regional dailies.",
  },
  {
    kicker: "Context",
    title: "Funding-gap data",
    body: "State development portals and Aspirational Districts dashboards.",
  },
] as const;

// A partner without a logo file yet renders as a labelled placeholder, as in the prototype.
const PARTNERS: { name: string; logo?: string }[] = [
  { name: "Node" },
  { name: "FFRH" },
  { name: "Project Tech4Dev", logo: "/partners/tech4dev.png" },
  { name: "Bridgespan" },
];

// The prototype's .card: surface fill, no border or shadow, tight padding.
const PLAIN_CARD = "gap-2 rounded-xl border-0 p-[13.2px] shadow-none";

function SectionHeading({ className, children }: { className?: string; children: React.ReactNode }) {
  return <h2 className={cn("text-2xl leading-[1.12] font-bold tracking-[-0.015em]", className)}>{children}</h2>;
}

export function HomePage() {
  return (
    <div className="sangam-ui bg-[color-mix(in_srgb,var(--color-accent-2-700)_15%,var(--color-bg)_85%)] leading-[1.55]">
      <div className="mx-auto max-w-(--page-max) px-(--page-pad) pt-14 text-sm tracking-[0.14em] text-terracotta-750 uppercase">
        Surfacing · Assessment · Narrative · Grantmaker Access · Matching
      </div>

      <section className="mx-auto grid max-w-(--page-max) items-center gap-12 px-(--page-pad) pt-6 pb-10 md:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <div>
          <h1 className="mb-6 max-w-[900px] text-4xl leading-[1.04] font-bold tracking-[-0.015em]">
            Where funders and NGOs actually meet
          </h1>
          <p className="mb-8 max-w-[560px] text-xl leading-[1.55] text-foreground/78">
            A base of funders, NGOs and media signal, with an agent on top. Ask who fits a mandate, which
            calls to chase, what a proposal still needs, or how an organisation is being covered to
            provide these matches. Every answer shows its sources and the steps it took.
          </p>
          <div className="flex flex-wrap gap-3">
            <Button
              asChild
              className="h-auto px-[26px] py-3 font-bold"
            >
              <Link href="/ask">Ask Sangam</Link>
            </Button>
            <Button
              asChild
              variant="outline"
              className="h-auto bg-transparent px-[26px] py-3 font-bold shadow-none hover:bg-foreground/7 hover:text-foreground"
            >
              <Link href="/registry">Explore the Registry</Link>
            </Button>
          </div>
        </div>
        <HeroSlides />
      </section>

      <section className="mx-auto max-w-(--page-max) px-(--page-pad) pt-4 pb-[72px]">
        <SectionHeading className="mb-2">Understanding how the Sangam agent works</SectionHeading>
        <p className="mb-4 max-w-[560px] text-sm text-foreground/70">
          Every answer is built from the base, not generated from general knowledge of the sector.
        </p>
        <ol className="home-steps">
          {STEPS.map((step, i) => (
            <li key={step.title} className="home-step">
              <div className="home-step-mark">
                <span className="home-step-num">{String(i + 1).padStart(2, "0")}</span>
                <span className="home-step-line" aria-hidden="true" />
              </div>
              <div className="home-step-text">
                <h3 className="home-step-title">{step.title}</h3>
                <p className="home-step-body">{step.body}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <section className="mx-auto max-w-(--page-max) px-(--page-pad) pt-[72px]">
        <SectionHeading className="mb-2">What feeds the base</SectionHeading>
        <div className="grid grid-cols-[repeat(auto-fit,minmax(230px,1fr))] gap-4">
          {SOURCES.map((source) => (
            <Card key={source.title} className={PLAIN_CARD}>
              <div className="text-xs tracking-[0.1em] text-primary uppercase">{source.kicker}</div>
              <div className="text-base leading-[1.2] font-bold">{source.title}</div>
              <p className="flex-1 text-sm opacity-80">{source.body}</p>
            </Card>
          ))}
        </div>
      </section>

      <section className="mx-auto max-w-(--page-max) px-(--page-pad) pt-[72px]">
        <SectionHeading className="mb-8">Partners and supporters</SectionHeading>
        <div className="flex flex-wrap gap-14">
          {PARTNERS.map((partner) =>
            partner.logo ? (
              <Image
                key={partner.name}
                src={partner.logo}
                alt={partner.name}
                width={197}
                height={61}
                className="h-12 w-[140px] object-contain"
              />
            ) : (
              <div
                key={partner.name}
                className="flex h-12 w-[140px] items-center justify-center rounded-md border border-dashed border-sand-400 text-xs text-sand-700"
              >
                {partner.name} logo
              </div>
            ),
          )}
        </div>
      </section>

      <section className="mx-auto max-w-(--page-max) px-(--page-pad) pt-16 pb-2">
        <Card className={cn(PLAIN_CARD, "items-center p-10 text-center")}>
          <SectionHeading className="mb-[22px]">Stay updated</SectionHeading>
          <label className="mb-3.5 flex w-[min(430px,100%)] cursor-pointer items-start gap-2.5 text-left text-xs text-sand-700">
            <Checkbox className="mt-px bg-background data-[state=checked]:border-sage-700 data-[state=checked]:bg-sage-700" />
            <span>
              I agree to receive occasional email updates from Sangam and can unsubscribe at any time. See
              the{" "}
              <Link href="/privacy" className="text-terracotta-750">
                Privacy Policy
              </Link>
              .
            </span>
          </label>
          <div className="flex w-[min(430px,100%)] gap-2.5">
            <Input type="email" placeholder="you@organisation.org" className="bg-sand-100" />
            <Button type="button" className="font-bold">
              Subscribe
            </Button>
          </div>
        </Card>
      </section>
    </div>
  );
}
