-- "Make a case" is the new step 3, so "Write the proposal" (now "Make a plan") and "Before you send it" move up one.
-- The list reads the stored summary, so its copy of the step moves too. Each file runs once, so nothing shifts twice.
UPDATE proposals
SET work = jsonb_set(work, '{stage}', to_jsonb((work->>'stage')::int + 1)),
    summary = CASE WHEN summary ? 'stage'
                   THEN jsonb_set(summary, '{stage}', to_jsonb((work->>'stage')::int + 1))
                   ELSE summary END
WHERE (work->>'stage')::int >= 3;
