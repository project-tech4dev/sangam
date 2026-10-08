# Design sync notes

Read `docs/DESIGN_SYSTEM.md` first; it has the mapping tables and the step-by-step procedure.

- **Target:** "Sangam Design System v2", `3b0e9aeb-8b17-4fa0-9194-2882f6b39edd` (pinned in
  `config.json`). The older "Sangam Design System" (`aeaa7276…`, owner Sid) predates Phase 1 and is
  replaced by v2; do not write to it.
- **Write access is V's to grant.** v2 is owned by V; a `write_files` from an account without
  edit access returns 403 "cannot edit this project" (8 Oct 2026, fixed once V granted it).
- **Do not run the `/design-sync` converter.** It builds a design system from a compiled
  component package (`dist/` + `.d.ts`) and replaces the project's components wholesale. Sangam
  has no package: most of its look is the classes in `frontend/app/globals.css`, and `Nav`,
  `AnswerCard`, `ScoreCard` and `UserMenu` need Next, Supabase or the live API. The project is
  hand-authored — plain-JSX reference components with inline styles over the tokens — and the
  UI-kit pages are written against that API. Sync by hand, file by file.
- **Layout is flat, not the converter's:** `components/<group>/<Name>.{jsx,d.ts,prompt.md}` with
  one `<group>.card.html` per group (`dialog.card.html` is a second surfaces card). Every card
  and UI-kit page starts with a `<!-- @dsCard group="…" -->` line.
- **Don't write `_ds_bundle.js`, `_ds_manifest.json`, `_adherence.oxlintrc.json` or
  `_ds_sync.json`.** Claude Design compiles the bundle from the `.jsx` sources (components and
  UI-kit files) when the project is next opened after `_ds_needs_recompile` is written —
  confirmed 8 Oct 2026. Nothing renders until someone opens it. Upload order: sentinel, files, sentinel.
- **Bundle global:** `window.SangamDesignSystemV2_3b0e9a` (Claude Design derives it from the
  project name and id). Every card and UI-kit page reads the components from it.
- **Fonts:** `fonts/PublicSans-*.woff2` come from `@fontsource/public-sans` (npm), latin and
  latin-ext, 400/500/600/700 and 400 italic. The app itself loads Public Sans via `next/font`.
- **Values come from the repo, not from rules of thumb:** read the repo component behind each
  design-system file before snapping a size or radius.

## Re-sync risks

- No render check runs (the converter's `package-validate` only applies to its own layout).
  Verification is opening the project, then the cards you touched and
  `ui_kits/sangam-web/index.html`.
- Off-scale values that remain on purpose: `EntityMark` sizes its initials at `size × 0.34`;
  `tweaks-panel.jsx` is a Claude Design scaffold with its own literal sizes.
