---
paths:
  - "backend/app/matching/**"
  - "backend/app/repositories/matching.py"
  - "backend/app/repositories/funder_matches.py"
  - "backend/app/api/routes/funder_matches.py"
  - "frontend/features/ask/views/FunderMatchView.tsx"
  - "frontend/features/ask/views/funder-match/**"
---

# Funder Match

Before changing this code, read `docs/ARCHITECTURE.md` §5 (Funder Match). It covers the match-v2 points and tiers, the theme-taxonomy comparison and saved runs with their RLS.
To change a rule, edit `rules.py`; to change points or tiers, edit `rubric.py`. Update §5 in the same PR.
