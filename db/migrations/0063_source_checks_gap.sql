-- 'gap': a page off the funder's own site that a full check read for one open gap; detail names the gap.
ALTER TABLE source_checks
    DROP CONSTRAINT source_checks_status_check,
    ADD CONSTRAINT source_checks_status_check
        CHECK (status IN ('unchanged', 'differs', 'minor', 'changed', 'unverified', 'dead', 'new', 'gap'));
