import Link from "next/link";
import type { ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { TermsIndex } from "./TermsIndex";
import type { SectionId } from "./sections";


const SHORT_VERSION = [
  "Your organisation owns its documents. Private vault files are visible only to your organisation's members and the FFRH staff supporting you.",
  "Sangam's agents run on third-party models from OpenAI and Anthropic. We use their business APIs, which do not train on your data by default, and we do not opt in to training.",
  "AI answers can be wrong. Every answer shows its sources and steps so you can check it before acting.",
  "We do not sell data, and we never share a private document with a funder unless you choose to.",
];

function Section({ id, n, title, children }: { id: SectionId; n: number; title: string; children: ReactNode }) {
  return (
  
    <section id={id} className="flex scroll-mt-24 flex-col gap-4">
      <h2 className="text-xl leading-[1.12] font-bold tracking-[-0.015em]">
        {n}. {title}
      </h2>
      {children}
    </section>
  );
}


function Rows({ rows }: { rows: [string, string][] }) {
  return (
    <div className="flex flex-col border-t">
      {rows.map(([label, body]) => (
        <div key={label} className="grid grid-cols-[160px_minmax(0,1fr)] gap-4 border-b py-3 text-sm">
          <strong>{label}</strong>
          <span>{body}</span>
        </div>
      ))}
    </div>
  );
}

function VaultCard({ kicker, children }: { kicker: string; children: ReactNode }) {
  return (
    <Card className="gap-2 rounded-xl border-0 p-5 shadow-none">
      <div className="text-[10.5px] font-bold tracking-[0.1em] text-terracotta-700 uppercase">{kicker}</div>
      <p className="text-sm text-foreground/78">{children}</p>
    </Card>
  );
}

export function TermsPage() {
  return (
    <div className="sangam-ui bg-[color-mix(in_srgb,var(--color-accent-2-700)_15%,var(--color-bg)_85%)]">
      <div className="mx-auto max-w-[1160px] px-8 pt-12 pb-20">
        <div className="mb-[18px] text-xs text-sand-700">
          <Link href="/" className="text-terracotta-700">Sangam</Link> / Terms &amp; Privacy
        </div>
        <h1 className="mb-3.5 text-4xl leading-[1.12] font-bold tracking-[-0.015em]">Terms &amp; Privacy</h1>
        <p className="mb-3.5 max-w-160 text-base text-foreground/75">
          One policy covering how you may use Sangam, how its AI agents work, and what happens to the documents
          and conversations you bring to it.
        </p>
        <div className="mb-12 flex flex-wrap items-center gap-2.5">
          <Badge className="border-0 bg-sand-100 text-sand-800">Last updated 26 September 2026</Badge>
          <Badge className="border-0 bg-terracotta-100 text-terracotta-800">
            Prototype draft — to be reviewed by counsel before launch
          </Badge>
        </div>

        <div className="grid items-start gap-14 md:grid-cols-[220px_minmax(0,1fr)]">
          <TermsIndex />

          <div className="flex max-w-[700px] flex-col gap-11 text-base leading-[1.65]">
            <Card className="gap-3 rounded-xl border-0 bg-sage-100 px-[26px] py-6 shadow-none">
              <div className="text-base font-bold text-sage-900">The short version</div>
              <ul className="flex flex-col gap-2 text-sm text-sage-800">
                {SHORT_VERSION.map((point) => (
                  <li key={point} className="flex gap-2.5">
                    <span className="mt-2 size-2 flex-none rounded-full bg-sage-700" />
                    <span>{point}</span>
                  </li>
                ))}
              </ul>
            </Card>

            <Section id="t-about" n={1} title="About these terms">
              <p>
                Sangam is a funder–NGO matching and proposal platform jointly operated by the Fractional Fund Raising
                Hub (FFRH), incubated within Node/SeSTA, and Project Tech4Dev. These terms apply to the public site,
                the Registry, Ask Sangam, and every signed-in feature. By using Sangam you agree to them. If you use
                Sangam on behalf of an organisation, you confirm you are authorised to accept these terms for it.
              </p>
            </Section>

            <Section id="t-access" n={2} title="Public and signed-in areas">
              <p>
                The home page, Registry, organisation profiles and methodology pages are open to anyone. Ask Sangam,
                organisation vaults, saved conversations, RFP matches and proposal tools require sign-in with a Google
                account.
              </p>
              <p>
                Each account is linked to one or more organisations with a role that decides what you can see. An NGO
                member sees their own organisation&apos;s vault and matches. FFRH staff see the organisations they
                support. Funders and ecosystem players see public records and whatever an organisation has chosen to
                share with them.
              </p>
            </Section>

            <Section id="t-registry" n={3} title="The public Registry">
              <p>
                Registry entries are compiled from public sources: the MCA CSR portal, BRSR and CSR-1 filings, NGO
                Darpan, organisation websites, annual reports and media coverage. Entries are reviewed against a shared
                rubric, but they may be incomplete or out of date, and placeholder entries are marked as such.
              </p>
              <p>
                If you represent an organisation listed in the Registry, you can ask us to correct, update or remove
                information about it. We will respond within 30 days.
              </p>
            </Section>

            <Section id="t-vaults" n={4} title="Organisation vaults">
              <p>Every organisation has a document vault that holds two kinds of material:</p>
              <div className="grid grid-cols-[repeat(auto-fit,minmax(240px,1fr))] gap-3.5">
                <VaultCard kicker="Public documents">
                  Annual reports, registrations and filings sourced automatically from your website and public
                  records. They&apos;re labelled with their source, and you can replace, update or hide any of them.
                </VaultCard>
                <VaultCard kicker="Private documents">
                  Files you upload yourself, including audited accounts, board minutes, draft proposals and anything
                  attached in Ask Sangam. Only your organisation&apos;s authorised members and supporting FFRH staff
                  can see them.
                </VaultCard>
              </div>
              <p>
                You keep ownership of everything in your vault. You give us a limited licence to store, index and
                process it only so that Sangam can answer your questions, score drafts and find matches for you. When a
                document you upload conflicts with a sourced one, your version takes precedence.
              </p>
              <p>
                Only upload material you have the right to share. Avoid personal data about beneficiaries or staff
                unless it is necessary, and redact it where you can.
              </p>
            </Section>

            <Section id="t-ai" n={5} title="How Sangam uses AI">
              <p>
                Sangam&apos;s agents read your question, retrieve relevant records from the base and your vault, score
                them against a rubric, and compose an answer. To do this we use:
              </p>
              <Rows
                rows={[
                  ["Embeddings", "Documents and records are converted into numerical representations so relevant passages can be found. Embeddings are stored with the same access rules as the document they came from."],
                  ["Agentic answers", "Language models plan steps, call retrieval tools and write the answer, citing the records used."],
                  ["Drafting and scoring", "Models suggest proposal text and score drafts against a funder's rubric. Criteria without evidence in the vault are scored as gaps, not estimated."],
                ]}
              />
              <p>
                AI output can be inaccurate, incomplete or out of date. It is decision support, not legal, financial or
                funding advice. Sangam does not make funding decisions, and no funder should rely on a Sangam score
                alone. Please check the cited sources before acting on an answer.
              </p>
            </Section>

            <Section id="t-vendors" n={6} title="Third-party AI providers">
              <p>
                Sangam currently sends prompts, retrieved passages and document text to <strong>OpenAI</strong> and{" "}
                <strong>Anthropic (Claude)</strong> through their business APIs to produce embeddings and answers. We
                may add or change providers and will list them here when we do.
              </p>
              <p>
                Under their API terms, these providers do not use API data to train their models by default. They may
                keep it for a limited period for abuse and safety monitoring. We do not opt in to model training, and
                we send only the passages needed for a given request, not your whole vault.
              </p>
              <p>
                Their handling of data is governed by their own terms and privacy policies, which we review before
                adopting any provider.
              </p>
            </Section>

            <Section id="t-collect" n={7} title="What we collect">
              <Rows
                rows={[
                  ["Account", "Your name and email address from Google sign-in, plus your organisation and role."],
                  ["Vault content", "Documents you upload and documents sourced for your organisation."],
                  ["Conversations", "Questions, voice input once transcribed, attachments, and the answers and reasoning steps produced."],
                  ["Usage", "Basic logs, such as pages visited, errors and device type, used to keep the service running and secure."],
                  ["Updates", "Your email address, if you tick the consent box to receive updates."],
                ]}
              />
            </Section>

            <Section id="t-use" n={8} title="How we use it, and what we don't do">
              <p>
                We use this information to run Sangam: to answer questions, keep conversation history, match
                organisations with funders and calls, support FFRH&apos;s work with the organisations it advises, and
                improve the rubric and retrieval.
              </p>
              <p>
                We do not sell personal or organisational data. We do not use private vault documents to train any AI
                model. We do not show a private document to a funder or another organisation unless someone with the
                right role in your organisation chooses to share it.
              </p>
            </Section>

            <Section id="t-retention" n={9} title="Storage, retention and deletion">
              <p>
                Conversations are saved to your account until you delete them. Vault documents are kept while your
                organisation&apos;s account is active. When you delete a document or conversation, we remove it, and
                any embeddings made from it, from active systems within 30 days. Backups roll off on their normal
                cycle.
              </p>
              <p>
                If an organisation leaves Sangam, its private vault is deleted within 90 days unless it asks for an
                export first. Public Registry entries may remain, since they come from public sources.
              </p>
            </Section>

            <Section id="t-rights" n={10} title="Your rights">
              <p>
                Under applicable law, including India&apos;s Digital Personal Data Protection Act, 2023, you can ask to
                see, correct or delete the personal data we hold about you, and you can withdraw consent to updates at
                any time. Organisation administrators can export or delete their vault. Write to us using the contact
                details below.
              </p>
            </Section>

            <Section id="t-acceptable" n={11} title="Acceptable use">
              <p>
                Don&apos;t upload material you have no right to share, misrepresent an organisation, try to reach
                another organisation&apos;s private vault, scrape the Registry at scale, or use Sangam to create
                misleading proposals or claims. We may suspend accounts that do.
              </p>
            </Section>

            <Section id="t-liability" n={12} title="Disclaimers and liability">
              <p>
                Sangam is an early-stage service provided as-is. We work to keep it accurate and available but cannot
                guarantee either. To the extent the law allows, we are not liable for decisions made on the basis of
                Sangam&apos;s content or AI output, or for losses arising from use of the service.
              </p>
            </Section>

            <Section id="t-contact" n={13} title="Changes and contact">
              <p>
                We will post changes here and update the date at the top. For material changes affecting vault data or
                AI providers, we will notify signed-in users first. For questions, corrections or data requests, write
                to{" "}
                <a href="mailto:privacy@sangam.example" className="text-terracotta-700">
                  privacy@sangam.example
                </a>
                .
              </p>
            </Section>
          </div>
        </div>
      </div>
    </div>
  );
}
