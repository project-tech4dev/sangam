-- Drop criteria_sets, which only the removed matching engine used.
--
-- 0023 created it on feat/matching-engine and never reached master; its file is
-- gone with the engine. A database that ran it keeps the table, so this drops
-- it there and is a no-op everywhere else.
DROP TABLE IF EXISTS criteria_sets;
