# Docs an agent relies on

`docs/ARCHITECTURE.md` (how the system works today) and `docs/HISTORY.md` (what shipped, and what is unfinished) stand in for reading the code. Keep them true:
- A PR that changes a tool, table, route, flow or setting described in ARCHITECTURE.md edits that section.
- A PR that ships something adds one line to HISTORY.md under its subsystem. A PR that leaves a plan half-done updates "Not finished".
