-- Turns asked in each chat; a person outside any organisation gets FREE_QUESTIONS Ask questions in all (#314).
ALTER TABLE threads ADD COLUMN IF NOT EXISTS questions integer NOT NULL DEFAULT 0;
