-- news_mentions held GDELT hits that never linked to an organisation (0 rows on staging, 11 Oct); 0044's stories
-- replace it. Kept apart from 0044 so staging can take the new tables before the code that stops reading this deploys.
DROP TABLE news_mentions;
