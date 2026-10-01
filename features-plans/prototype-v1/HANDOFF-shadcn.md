# Sangam → shadcn/ui handoff

The prototype is styled from one token sheet (`styles.css`). Its `:root` block carries the Sangam tokens **and** the same values under shadcn/ui's variable names, so a Next.js + Tailwind v4 + shadcn app can adopt the look by pasting that block into `app/globals.css`.

## Package contents
- `Sangam Prototype.html` — every page in one offline file (hash routes: `#home`, `#registry`, `#sesta`, `#ant`, `#apf`, `#ask`, `#resources`, `#methodology`, `#taxonomy`, `#terms`).
- `sangam-theme.css` — drop-in theme for React/Tailwind v4/shadcn: `:root` tokens, `@theme inline` mapping, and brand ramps as `terracotta-*`, `sage-*`, `sand-*` utilities.
- `sangam-prototype.css` — the prototype's full stylesheet (tokens + `.btn`/`.card`/`.tag` classes). Reference only; the React app should use shadcn components instead of these classes.
- `CONTEXT.md` — decisions and open questions.

## Setup
1. `npx shadcn@latest init`, delete the generated `:root`/`.dark`/`@theme inline` blocks from `globals.css`, and add `@import "./sangam-theme.css";` after the Tailwind imports.
2. Font: Public Sans (Google Fonts, weights 400/700). Set `--font-sans` to it.
3. Radius: stock shadcn, `--radius: 0.625rem`. Buttons, inputs, badges and tabs use `rounded-md`; cards and dialogs use `rounded-xl`. No overrides needed.

## Type scale → Tailwind
| Token | px | Tailwind |
| --- | --- | --- |
| `--fs-xs` | 12 | `text-xs` |
| `--fs-sm` | 14 | `text-sm` |
| `--fs-md` | 16 | `text-base` |
| `--fs-lg` | 20 | `text-xl` |
| `--fs-xl` | 24 | `text-2xl` |
| `--fs-2xl` | 36 | `text-4xl` |

Two weights only: `font-normal`, `font-bold`.

## Prototype class → shadcn component
| Prototype | shadcn |
| --- | --- |
| `.btn.btn-primary` | `<Button>` (default) |
| `.btn.btn-secondary` | `<Button variant="outline">` |
| `.btn.btn-ghost` | `<Button variant="ghost">` |
| `.btn-icon` | `<Button size="icon">` |
| `.tag`, `.tag-accent`, `.tag-accent-2`, `.tag-neutral`, `.tag-outline` | `<Badge>`: default / `secondary` / `outline`; add one `accent` variant for the sage tag |
| `.card` + `.card-kicker/-title/-body/-meta` | `<Card>` + `CardHeader`, `CardTitle`, `CardDescription`, `CardContent`, `CardFooter` |
| `.input`, `textarea.input` | `<Input>`, `<Textarea>` |
| consent checkbox | `<Checkbox>` + `<Label>` |
| `.seg` / tab rows (profile tabs, Registry filters) | `<Tabs>` / `<ToggleGroup>` |
| `.dialog-backdrop` + `.dialog` (Google sign-in) | `<Dialog>` |
| `.table` | `<Table>` |
| user avatar menu | `<Avatar>` + `<DropdownMenu>` |
| Ask Sangam left rail (conversations, use cases, Doc Vault) | `<Sidebar>` (uses the `--sidebar-*` tokens) |
| "Why this match" / step-trace expanders | `<Collapsible>` or `<Accordion>` |
| confidence / vault completeness bars | `<Progress>` |
| hero use-case slideshow | `<Carousel>` (fade plugin, 8s autoplay) |
| Terms page section index | plain list + scroll-spy; `<ScrollArea>` optional |
| map (profiles → Geography) | stays as Leaflet (`react-leaflet`), not shadcn |

## Not covered by shadcn
- District map: Leaflet + OSM tiles; see `DistrictMap.html`.
- DRAFT watermark: a page-level fixed overlay. Remove it once a page enters build.
