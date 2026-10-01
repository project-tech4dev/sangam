-- db/seed/examples/kabil_gramseva_proposal.sql
-- EXAMPLE ONLY: a draft KABIL proposal to the SBI Gram Seva RFP, to exercise the
-- proposals table and check_template(). Not real application data; do not load in production.

BEGIN;
INSERT INTO proposals (org_id, funder_id, rfp_id, template_id, title, status, requested_amount, duration_months)
SELECT o.id, f.id, r.id, t.id, 'Gram Seva: integrated village development, Udalguri (example)', 'drafting', 35000000, 24
FROM orgs o, funders f, rfps r, proposal_templates t
WHERE o.slug = 'kabil' AND f.slug = 'sbi-foundation' AND r.title LIKE 'SBI Gram Seva%' AND t.name = 'SBI Gram Seva RFP 2024'
  AND NOT EXISTS (SELECT 1 FROM proposals p WHERE p.org_id = o.id AND p.rfp_id = r.id);
COMMIT;
