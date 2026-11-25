-- Nine funder types with a CHECK, the five-way roll-up as a generated column, and money_origin for FCRA (#324).
-- Old values map mechanically; a family trust keeps its old label in profile.source_funder_type. Any other value
-- outside the nine becomes 'other' and keeps its label the same way, so no row fails the new CHECK.

UPDATE funders
   SET profile = profile || jsonb_build_object('source_funder_type', funder_type)
 WHERE btrim(coalesce(funder_type, '')) <> '' AND funder_type NOT IN (
         'corporate_csr', 'corporate_foundation', 'other', 'csr_company', 'csr_foundation', 'private_foundation',
         'hni', 'intermediary', 'international_agency', 'bilateral_multilateral', 'government');

UPDATE funders
   SET funder_type = CASE
         WHEN funder_type = 'corporate_csr' THEN 'csr_company'
         WHEN funder_type = 'corporate_foundation' THEN 'csr_foundation'
         WHEN funder_type IN ('family_trust', 'family_trust_network') THEN 'private_foundation'
         WHEN btrim(funder_type) = '' THEN NULL
         WHEN funder_type IN ('csr_company', 'csr_foundation', 'private_foundation', 'hni', 'intermediary',
                              'international_agency', 'bilateral_multilateral', 'government', 'other')
           THEN funder_type
         ELSE 'other'
       END
 WHERE funder_type IS NOT NULL;

ALTER TABLE funders ADD COLUMN IF NOT EXISTS money_origin text NOT NULL DEFAULT 'unknown';

-- Reviewed by slug (docs/features/2026-11-25-funder-types-and-fcra.md). A slug this database lacks is skipped.
-- money_origin is set only where the funder's own website shows where its money comes from; that is the source.
UPDATE funders f
   SET funder_type = v.funder_type,
       money_origin = v.money_origin,
       profile = f.profile || CASE WHEN v.money_origin <> 'unknown' AND f.website IS NOT NULL
                                   THEN jsonb_build_object('money_origin_source', f.website)
                                   ELSE '{}'::jsonb END
  FROM (VALUES
    ('brot-f-r-die-welt-bread-for-the-world', 'international_agency', 'foreign'),
    ('dreik-nigsaktion-der-katholischen-jungschar-sterreichs-dka', 'international_agency', 'foreign'),
    ('katholische-frauenbewegung-sterreichs-kfb', 'international_agency', 'foreign'),
    ('misereor', 'international_agency', 'foreign'),
    ('terre-des-hommes-deutschland-e-v', 'international_agency', 'foreign'),
    ('stichting-liliane-fonds', 'international_agency', 'foreign'),
    ('global-greengrants-fund', 'intermediary', 'foreign'),
    ('women-s-fund-asia', 'intermediary', 'foreign'),
    ('the-resilience-fund-for-women-in-global-value-chains', 'intermediary', 'foreign'),
    ('paul-hamlyn-foundation', 'private_foundation', 'foreign'),
    ('stiftung-childaid-network', 'private_foundation', 'foreign'),
    ('mariwala-health-foundation', 'private_foundation', 'unknown'),
    ('rajiv-gandhi-foundation', 'private_foundation', 'unknown'),
    ('selco-foundation', 'private_foundation', 'unknown'),
    ('caring-friends', 'hni', 'unknown'),
    ('ekaimpact-social-foundation', 'intermediary', 'unknown'),
    ('impact-foundation-india', 'intermediary', 'unknown'),
    ('childline-india-foundation', 'government', 'unknown'),
    ('roots-to-branches-foundation', 'other', 'unknown')
  ) AS v(slug, funder_type, money_origin)
 WHERE f.slug = v.slug;

ALTER TABLE funders
  ADD CONSTRAINT funders_funder_type_known CHECK (funder_type IN (
    'csr_company', 'csr_foundation', 'private_foundation', 'hni', 'intermediary',
    'international_agency', 'bilateral_multilateral', 'government', 'other')),
  ADD CONSTRAINT funders_money_origin_known CHECK (money_origin IN ('domestic', 'foreign', 'mixed', 'unknown'));

-- The roll-up the Registry and reports use; NULL while the type is not researched.
ALTER TABLE funders ADD COLUMN IF NOT EXISTS funder_group text GENERATED ALWAYS AS (
  CASE
    WHEN funder_type IN ('csr_company', 'csr_foundation') THEN 'corporate'
    WHEN funder_type = 'hni' THEN 'hni'
    WHEN funder_type IN ('private_foundation', 'intermediary', 'international_agency') THEN 'philanthropy'
    WHEN funder_type IN ('bilateral_multilateral', 'government') THEN 'govt'
    WHEN funder_type = 'other' THEN 'other'
  END) STORED;
