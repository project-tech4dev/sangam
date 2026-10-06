-- Versions of the funder-matching criteria file, with a draft -> active -> retired lifecycle.
--
-- The engine reads the ACTIVE row, never the newest: loading a draft changes no answer until
-- someone activates it, and a rollback is re-activating a retired row. Rows are never deleted,
-- so any past assessment can be re-run against the exact criteria it was made with.

CREATE TABLE criteria_sets (
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  set_name     text NOT NULL,
  version      int  NOT NULL,
  status       text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'active', 'retired')),
  content      jsonb NOT NULL,
  content_hash text NOT NULL,
  git_sha      text,
  engine_api   int  NOT NULL,
  loaded_at    timestamptz NOT NULL DEFAULT now(),
  activated_at timestamptz,
  retired_at   timestamptz,
  activated_by text,
  UNIQUE (set_name, version)
);

-- One live version per set: activation retires the previous one in the same transaction.
CREATE UNIQUE INDEX criteria_sets_one_active ON criteria_sets (set_name) WHERE status = 'active';
