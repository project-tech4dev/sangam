-- What a funder requires of an applicant, as its own rows.
--
-- funder-intake-research pulls this twice: field 4 splits stated eligibility
-- into the statutory restatement (Rule 4 of the Companies (CSR Policy) Rules
-- copied into the policy) and the funder's OWN additional bar, and field 6
-- pulls hard disqualifiers separately again. Until now the only home was
-- rfps.eligibility, which is wrong twice over: it hangs off an open call, and
-- most funders have none — their CSR page is a statutory annexure describing
-- money already spent — and it is one jsonb blob with one source_url, so the
-- split the skill works to produce arrives as three indistinguishable strings.
--
-- Deliberately on the funder and not on rfps, the same line 0019 drew for
-- grant size: this is the funder's standing posture across all its giving.
-- rfps.eligibility stays exactly as it is and means a requirement printed in
-- one call. A sentence can be true in both places; that is two rows.
CREATE TABLE funder_eligibility (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  funder_id bigint NOT NULL REFERENCES funders(id) ON DELETE CASCADE,
  -- Three values, and the first two are field 4's split. A funder that only
  -- restates the law has no bar of its own, and reporting those together says
  -- something false. Mirrored by FunderEligibilityFinding.criterion_kind.
  kind text NOT NULL CHECK (kind IN ('statutory_restatement', 'own_bar', 'disqualifier')),
  -- The funder's wording, verbatim. Two funders restating Rule 4 in different
  -- words are two rows, not a normalisation problem: the catalog records what
  -- a source said.
  criterion text NOT NULL CHECK (length(btrim(criterion)) >= 10),
  notes text,
  -- The provenance set funder_partners and funder_footprints carry. Narrower
  -- than CLAUDE.md's full list on purpose: the writers name their columns
  -- explicitly, and matching the neighbouring table is what keeps _upsert
  -- uniform across the funder family.
  source_url text, source_name text, fetched_at timestamptz, as_of text,
  document_id bigint REFERENCES documents(id), archive_url text,
  UNIQUE NULLS NOT DISTINCT (funder_id, kind, criterion)
);
CREATE INDEX funder_eligibility_funder_idx ON funder_eligibility (funder_id, kind);

-- The document checklist (field 5) is deliberately NOT here. "Submit an
-- audited balance sheet" is what to send, not who may apply, and a published
-- checklist can run to 32 items — it would outnumber the eligibility rows and
-- make "how many bars does this funder set" unanswerable. Adding
-- 'document_required' to the CHECK is the one-line change if that flips.
