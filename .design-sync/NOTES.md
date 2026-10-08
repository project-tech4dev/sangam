# Design sync notes

Read `docs/DESIGN_SYSTEM.md` first; it has the mapping tables and the step-by-step procedure.

- **Target:** "Sangam Design System v2", `3b0e9aeb-8b17-4fa0-9194-2882f6b39edd` (pinned in
  `config.json`). The older "Sangam Design System" (`aeaa7276…`, owner Sid) predates Phase 1 and is
  replaced by v2; do not write to it.
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
  `_ds_sync.json`.** Claude Design is expected to compile the bundle from the `.jsx` sources when
  the project is opened after `_ds_needs_recompile` is written — unconfirmed (see risks). If it
  never does, the fallback is building `_ds_bundle.js` with esbuild the way the skill's
  `lib/bundle.mjs` does, which needs a new upload plan that includes it. Upload order: sentinel, files, sentinel.
- **Bundle global:** cards and UI-kit pages read the components from
  `window.SangamDesignSystem…`. See "Re-sync risks" for the exact name.
- **Fonts:** `fonts/PublicSans-*.woff2` come from `@fontsource/public-sans` (npm), latin and
  latin-ext, 400/500/600/700 and 400 italic. The app itself loads Public Sans via `next/font`.
- **Values come from the repo, not from rules of thumb:** read the repo component behind each
  design-system file before snapping a size or radius.

## Re-sync risks

- The bundle global name. The first v2 upload used a lookup by prefix
  (`Object.keys(window).find((k) => k.startsWith("SangamDesignSystem"))`) because the bundle
  had not been compiled yet; replace it with the exact name once `_ds_bundle.js` exists and
  record the name here.
- Bundle compilation was not verified at upload time: if a card shows old or missing
  components, open the project once and re-check `_ds_bundle.js`'s `sourceHashes`.
- No render check ran (the converter's `package-validate` only applies to its own layout).
  Verification is opening the cards and `ui_kits/sangam-web/index.html`.
- Off-scale values that remain on purpose: `EntityMark` sizes its initials at `size × 0.34`;
  `tweaks-panel.jsx` is a Claude Design scaffold with its own literal sizes.
