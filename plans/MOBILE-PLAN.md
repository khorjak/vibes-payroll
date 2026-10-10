# Mobile / responsive UI plan

> Status: **All three phases implemented**; the Alpine/HTMX finding is fixed. The optional card view was not built.

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

### Finding while verifying (fixed after Phase 1)

- The CSP (`main.py`) has no `'unsafe-eval'`, so standard Alpine.js cannot
  evaluate any expression. Every `x-data`/`x-show`/`@click` in the app fails;
  `x-show` + `x-cloak` elements stay visible (e.g. flash messages cannot be
  dismissed, void-reason panels are always open).
- The HTMX `<script>` SRI hash does not match what `unpkg.com/htmx.org@1.9.12`
  serves (it redirects to `/dist/htmx.min.js`), so browsers refuse to run HTMX.
  HTMX-only behaviour (live search, partial swaps) silently falls back or does
  nothing.
- **Fixed:** Alpine was removed (its 8 uses were simple show/hide toggles) in
  favour of a delegated `data-toggle` / `data-dismiss` script in `layout.html`,
  keeping the CSP free of `'unsafe-eval'`. HTMX is pinned to
  `.../dist/htmx.min.js` with its published hash. Turning HTMX on exposed a
  latent timesheet bug: `hx-include="find input"` sent only the CSRF token, so
  autosave stored 0 hours, and `from:input` re-posted every row; both fixed.

## Phase 2 — page sweep (done)

- **Tables.** 13 tables sat directly in an `overflow-hidden` card, so on a phone
  their right-hand columns were cut off and unreachable. Those cards are now
  `overflow-x-auto`, as are the payroll register card and the benefit cards on
  the company and employee pages. The paycheck detail tables needed no scroller:
  they had been squeezed by a two-column grid that now stacks below `lg`.
  `tests/test_layout.py` fails if a `<table>` sits directly inside an
  `overflow-hidden` wrapper again.
- **Grids.** Form and summary grids are `grid-cols-1 sm:grid-cols-N` (employee
  form, company form, benefit plan edit, new pay period, the company and profile
  add forms, reports index, paycheck summary). The label/value detail grids on
  the employee profile, company detail and SUTA summary stay two columns; they
  read fine at 375px.
- **Headers.** Page header rows got `flex-wrap gap-3` rather than a
  `flex-col`/`sm:flex-row` switch: the actions drop below the title only when
  they don't fit, and desktop is unchanged. The pay period and paycheck action
  groups wrap too.
- **Inline forms.** Mark Remitted stacks its reference field above the button
  on phones; the void reason form wraps. Save Check # and Mark Paid already fit.
- Verified in headless Chromium on 37 pages with seeded data (open, draft and
  paid runs, a benefit liability): at 375px no element overflows the content
  area unless it is inside a horizontal scroller (9 pages failed before); at
  1280px nothing changed. Void panel and remit form checked at 375px.

## Phase 3 — polish where phones are actually used (done)

- **Columns hidden below `sm`** (`hidden sm:table-cell` on the `th` and every
  `td`, including the pay period totals row): employee list (Department, Hire
  Date), pay runs (Pay Period, Frequency, Checks), pay period paychecks
  (Pre-tax Ded., Taxes, Check #), users (Created). The employee list and pay
  runs now fit a 375px screen; pay period paychecks and users still scroll
  about 100px, which was accepted rather than hiding Status or Companies.
  `tests/test_layout.py` fails if a row hides a different set of columns
  than its header (cells would shift under the wrong heading).
- **Show all columns** (phones only, `templates/_all_cols_toggle.html` above
  each of those four tables): a `data-all-cols` button toggles
  `body.show-all-cols`, which a rule in the `layout.html` phone media query
  turns into `display: table-cell` for the hidden columns. The choice is kept
  in `localStorage` (`showAllCols`), so it covers all four tables and survives
  navigation and the employee live-search swap. Added because hiding columns
  with no way back was too restrictive.
- **Form fields are 16px below `md`** (one `!important` rule in the
  `layout.html` phone media query; the standalone login page uses
  `text-base sm:text-sm`). iOS zooms the page in when a field under 16px gets
  focus, which hit every form in the app. The payroll register filter selects
  got `max-w-full`, as their long option text then overflowed by ~12px.
- **Timesheet:** hour inputs are ~42px tall below `md` (34px from `md`), use
  `inputmode="decimal"` for a numeric keypad, and the employee name column is
  `sticky left-0` so it stays in view while swiping across the hour columns.
- **Card view: not built.** After Phase 2 and the hidden columns, the tables
  scroll at most ~100px; revisit if users on phones find that awkward.
- Verified in headless Chromium at 375px and 1280px: hidden columns gone on
  phones and shown on desktop, header/body/footer cells line up, timesheet
  name stays put while scrolling and autosave still works, 0 of 37 pages
  overflow at either width.

## Out of scope

Pay stub PDF (WeasyPrint, fixed page) and report print output.
