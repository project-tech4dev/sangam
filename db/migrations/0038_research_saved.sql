-- What the last save of this research row wrote, per concept, so Import's Done step can show
-- "16 → 41 facts" after the fact. A dry-run compare cannot: once written, every row reads as "same".
-- Numbered 0038: 0036 and 0037 are taken on fix/pr100-port.
ALTER TABLE entity_research
    ADD COLUMN saved    jsonb,
    ADD COLUMN saved_at timestamptz;
