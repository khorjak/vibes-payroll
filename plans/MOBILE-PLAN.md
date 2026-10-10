# Mobile / responsive UI plan

> Status: **Phase 1 implemented.** Phases 2-3 pending.

## Problem

On a phone the fixed 224px sidebar took over half of a 375px screen, and the rest
of the UI was desktop-only: 18 of 20 templates with tables had no horizontal
scroll wrapper, 17 `grid-cols-N` grids had no mobile fallback, 16 page headers
put title and action buttons on one row, and almost nothing used `sm:`/`md:`.

## Decisions

- **Drawer, not a bottom tab bar.** Seven nav items are too many for a tab bar,
  and a drawer keeps a single nav markup.
- **Breakpoint `md` (768px).** Tablets in portrait get the drawer too.
- **Wide tables scroll inside their card first** (Phase 2); card layouts only
  where scrolling still hurts (Phase 3).

## Phase 1 — layout shell (done)

`templates/layout.html` only, plus side padding on the standalone login page.

- Below `md` the sidebar is an off-canvas drawer: hamburger in the top bar,
  close button, dimmed backdrop, Esc to close, focus moves into the drawer on
  open and back to the hamburger on close. Closed drawer links are out of the
  tab order (`visibility: hidden`).
- Implemented with a `<style>` media query on `body.nav-open` and a small inline
  vanilla script, **not** Alpine or HTMX (see Finding below).
- Top bar: `px-4 md:px-6`, breadcrumb truncates, username hidden below `sm`,
  company switcher/name capped at 9rem below `sm`.
- Content `p-4 md:p-6`, flash `mx-4 md:mx-6`, nav links ~40px tall on phones.
- Verified in headless Chromium at 375px and 1280px: drawer open/close by
  button, backdrop, Esc and navigation; no horizontal page scroll at 375px on
  the employee list; desktop unchanged.

### Finding while verifying (not fixed in Phase 1)

- The CSP (`main.py`) has no `'unsafe-eval'`, so standard Alpine.js cannot
  evaluate any expression. Every `x-data`/`x-show`/`@click` in the app fails;
  `x-show` + `x-cloak` elements stay visible (e.g. flash messages cannot be
  dismissed, void-reason panels are always open).
- The HTMX `<script>` SRI hash does not match what `unpkg.com/htmx.org@1.9.12`
  serves (it redirects to `/dist/htmx.min.js`), so browsers refuse to run HTMX.
  HTMX-only behaviour (live search, partial swaps) silently falls back or does
  nothing.
- Fix options: switch to the Alpine CSP build (`@alpinejs/csp`, requires moving
  inline expressions into `Alpine.data` components) or allow `'unsafe-eval'`;
  pin HTMX to `.../dist/htmx.min.js` with the correct integrity hash.

## Phase 2 — page sweep (all templates)

- Wrap every table in `overflow-x-auto`.
- `grid-cols-N` → `grid-cols-1 sm:grid-cols-N` (employee form/profile, company
  form/detail, paycheck detail, reports index, SUTA, etc.).
- Page headers `flex-col gap-3 sm:flex-row sm:justify-between`; action groups
  `flex-wrap` (pay period page: Calculate / Approve / Mark Paid + check number).
- Inline row forms (Mark Remitted, void reason, Save Check #) stack on phones.

## Phase 3 — polish where phones are actually used

- Hide low-value columns below `sm` on employee list, pay runs, pay period
  paychecks, users.
- Check timesheet grid input sizes for thumb editing.
- Optional card view for employee list / pay period paychecks if scrolling
  still feels bad after Phase 2.

## Out of scope

Pay stub PDF (WeasyPrint, fixed page) and report print output.
