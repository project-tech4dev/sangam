-- Turns asked in each chat; a person outside any organisation gets FREE_QUESTIONS Ask questions in all (#314).
-- Never negative: authenticated may INSERT its own threads row through the Data API, and a negative count
-- would cancel the limit.
ALTER TABLE threads ADD COLUMN IF NOT EXISTS questions integer NOT NULL DEFAULT 0
  CONSTRAINT threads_questions_not_negative CHECK (questions >= 0);
