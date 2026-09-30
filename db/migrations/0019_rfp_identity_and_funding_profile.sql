-- Two things the fundraiser's brief needs and the schema could not hold.

-- 1. rfps had no unique constraint of any kind, so re-reading a funder's calls
-- page grew a second copy of every call. The key includes `deadline` on
-- purpose: an annual call re-issued for the next cycle is a different
-- opportunity to an NGO, not an edit of the old one. A deadline EXTENDED on
-- the same call is the case this gets wrong, and it is the rarer one — the
-- extension arrives as a new row and the old one ages out via `status`.
--
-- NULLS NOT DISTINCT because funder_id and deadline are both nullable and
-- Postgres would otherwise treat every such row as unique.
ALTER TABLE rfps
  ADD CONSTRAINT rfps_identity UNIQUE NULLS NOT DISTINCT (funder_id, title, deadline);

-- 2. Four facts a funder publishes about how it gives, which had no column.
-- Deliberately on funders and not on rfps: these describe the funder's posture
-- across all its giving, where rfps.amount_min/max describe one call.
ALTER TABLE funders
  -- How an NGO can approach them at all. The single most useful field in the
  -- brief for a fundraiser, and the one most often buried in prose.
  ADD COLUMN intake_mode text
    CHECK (intake_mode IN ('open', 'rolling', 'invitation_only', 'rfp_only', 'closed', 'unknown')),
  -- What the funder SAYS about funding others. The count of
  -- funder_csr_spend.via_agency is what it DID; the two are reported side by
  -- side and never reconciled into one number.
  ADD COLUMN funds_external boolean,
  ADD COLUMN typical_duration_months int
    CHECK (typical_duration_months IS NULL OR typical_duration_months > 0),
  -- A stated grant band, e.g. "we fund projects of Rs 25 lakh to Rs 2 crore".
  -- INR, like every other amount here.
  ADD COLUMN grant_size_min numeric CHECK (grant_size_min IS NULL OR grant_size_min >= 0),
  ADD COLUMN grant_size_max numeric CHECK (grant_size_max IS NULL OR grant_size_max >= 0),
  ADD CONSTRAINT funders_grant_band CHECK (
    grant_size_min IS NULL OR grant_size_max IS NULL OR grant_size_max >= grant_size_min
  );

-- No column for "total CSR budget if separately disclosed". prescribed_csr is
-- the statutory 2% obligation; a voluntarily published budget is a PLAN, and
-- the plan-versus-spend distinction is the one this whole pipeline enforces.
-- It stays in funder_csr_years.notes with the funder's wording, and the report
-- states it beside the obligation rather than in place of it.
