# Multi-Company Follow-Up: Defects Found After Implementation

> Status: **Implemented** (all 8 items). 404 tests pass.
>
> Notes from implementation, where reality differed from the plan as written:
>
> - **#1** — the planned "skip cloning if a matching row exists" guard on `upgrade()` does not work: at clone time `company_id` is still NULL on every row (the column was only just added), so a leftover clone never matches `WHERE company_id = :co`. Replaced with a single `_collapse_duplicate_codes()` helper called by **both** directions — upgrade absorbs leftovers before cloning, downgrade collapses before de-scoping. Simpler and symmetric.
> - **#3** — caching on the `User` instance was not sufficient on its own and **initially re-opened the revocation hole**, exactly as the plan warned. SQLAlchemy's identity map returns the *same* `User` object when a Session is reused, so the memo survived the request. `tests/test_multi_company.py::test_revoked_access_takes_effect_without_relogin` caught it. Fixed by clearing the attribute inside `get_current_user` — the one dependency every scoped route passes through — which makes the cache provably request-scoped.
> - **#3, extra** — the dashboard (`main.py`) hand-rolled its own `SessionLocal` and never got the stash, so `/` still double-read. Converted it to the normal `CurrentUser` / `ActiveCompany` / `get_db` dependencies; the 401 handler produces the same login redirect as the old manual session check.
> - **#2** — `save_timesheet_row`'s mismatch branch returns a 422 *HTTPException* rather than a form re-render, because that route answers HTMX row saves, not a full page.

## Outcome

Measured SELECTs per request, before → after (preparer with two companies):

| Path | total | `user_companies` reads |
|---|---|---|
| `/` | 8 → **6** | 2 → **1** |
| `/employees/` | 9 → **6** | 3 → **1** |
| `/payroll/` | 9 → **6** | 3 → **1** |
| `/reports/tax-liability?company_id=-1&year=2026` | 11 → **7** | 4 → **1** |

Migration round-trip, previously compounding 2 → 4 → 6 → 10 across three cycles, now stays flat at 4 and returns to 2 on every downgrade — pinned by `tests/test_migrations.py`.

Test count 395 → 410.

**Post-implementation verification** (the four risk areas, each checked against running code, not by reading alone):

| Area | Check | Result |
|---|---|---|
| `_collapse_duplicate_codes` | Called before the codes SELECT in `upgrade()`; employees repointed before any delete, so no FK is left dangling | Confirmed; `tests/test_migrations.py` (8 tests) |
| NULL rates | Original `IFNULL(rate, -1)` sentinel would merge a genuine `-1` rate with an unrated code, silently changing an employee's WC rate | **Defect found and fixed** — now uses null-safe `IS`; 2 tests pin that NULL and `-1` stay distinct |
| `_company_ids_cache` | Only `main.py`'s `company_context` fallback obtains a `User` outside `get_current_user` *and* calls a scope function; it uses its own `SessionLocal` closed in `finally`, so the instance never survives the call | Safe; guarded by `test_revoked_access_takes_effect_without_relogin` |
| Partial routes | `company_id` omitted → empty list, never "all"; out-of-scope → 404 | 4 tests in `TestDependentOptionRoutes` |
| 422 vs 404 | Out-of-scope company and out-of-scope employee both still 404; only in-scope mismatch is 422 | 3 tests in `TestInScopeMismatchVsOutOfScope` |
| Derived report totals | Consolidated totals must equal the sum of per-company runs — including `employee_count`, which sums per-period distinct counts and so partitions cleanly by company | Equal; 4 tests in `TestConsolidatedTotalsMatchPerCompany` |
>
> Companion to `plans/MULTI-COMPANY-PLAN.md` (Implemented). Everything here was found *after* that work shipped, either while verifying it or while exercising the running app. None of it is a tenancy hole — the 404-on-out-of-scope boundary holds and `tests/test_multi_company.py` proves it. These are correctness, usability, performance and test-quality defects in the surrounding machinery.

Every item below was reproduced against a real database or a running app; the evidence is recorded with each one so none of it has to be re-derived.

## Severity summary

| # | Issue | Class | Severity |
|---|---|---|---|
| 1 | Migration round-trip duplicates workers comp codes | Data correctness | **High** |
| 2 | Stale dependent dropdowns; off-cycle dead-ends on a hard 404 | Usability | **Medium** |
| 3 | `user_companies` re-read 2–4× per request; switcher opens its own session | Performance | Medium |
| 4 | `user_companies` audit rows carry the wrong `record_id` | Audit integrity | Medium |
| 5 | Consolidated payroll register lists indistinguishable periods | Usability | Low |
| 6 | `tax_liability` computes every row twice when consolidated | Performance | Low |
| 7 | `test_no_beta_data_in_response_bodies` passes vacuously | Test quality | Low |
| 8 | Inactive users get no company assignments on upgrade | Behaviour | Decide & document |

---

## 1. Migration round-trip duplicates workers comp codes

**Severity: High** — silent, compounding data growth.

`alembic/versions/b7f2a91c40d3_multi_company_scoping.py` clones shared WC codes so each company gets its own copy (correct, and necessary to keep historical paychecks reconcilable). Its `downgrade()` drops `company_id` but **leaves the cloned rows behind**. A subsequent `upgrade` then treats those clones as ordinary global codes and clones them again.

**Reproduced** on a DB seeded with 2 codes (`8810` shared by both companies, `9999` unreferenced):

```
start:              2 codes
after upgrade  #1:  4
after downgrade:    4     <- clones survive
after upgrade  #2:  6
after downgrade:    6
after upgrade  #3:  10
```

Growth compounds. A rollback-and-retry during a botched deploy silently fills every company's WC picker with identical duplicate entries. Rates are preserved, so payroll figures stay correct — this is junk data and operator confusion, not miscalculation.

### Fix

Make `downgrade()` a true inverse by collapsing duplicates as it de-scopes. Once `company_id` is gone the codes are global again, so two rows identical on `(ncci_code, description, rate_per_100_wages)` are by definition the same code — merging them is correct, not lossy.

In `downgrade()`, **before** dropping the column:

1. Group codes by `(ncci_code, description, rate_per_100_wages)`.
2. Keep the lowest `id` in each group.
3. Repoint `employees.workers_comp_code_id` from every other member of the group to the survivor.
4. Delete the non-survivors.
5. Then drop `company_id` as it does today.

Add a guard to `upgrade()` as belt-and-braces: skip cloning when a matching `(company_id, ncci_code, description, rate)` row already exists, so even a hand-rolled partial rollback cannot double up.

**Verification:** extend the round-trip harness to assert the code count returns to its starting value after `upgrade → downgrade`, and stays flat across three full cycles. This must be an automated test, not a manual script — it is the only defect here that corrupts data.

---

## 2. Stale dependent dropdowns; off-cycle dead-ends on a hard 404

**Severity: Medium** — a legitimate multi-company workflow is unreachable through the UI.

Both forms render company-dependent dropdowns for the *active* company, but the company `<select>` has no `hx-get` and no `onchange` (`templates/employees/form.html:101`, `templates/payroll/off_cycle.html:15`). Pick a different company and the dependent list is stale.

**Reproduced** with the active company Alpha, picking Beta in the form:

| Form | Stale list | Submit result |
|---|---|---|
| `/payroll/off-cycle/new` | employee options are Alpha's | **404, no form error** |
| `/employees/new` | WC options are Alpha's | 422 with "belonging to this company" |

The employee form degrades acceptably — a clear field error. Off-cycle does not: following the UI honestly produces a bare 404 page with no explanation and no way forward.

### Fix

**a. Cascade the dependent selects.** Add `hx-get` on each company `<select>`, targeting a partial that re-renders the dependent select, matching the HTMX idiom already used in `templates/employees/list.html`:

- New `GET /employees/wc-code-options?company_id=` → renders `templates/employees/_wc_options.html`, reusing `_company_wc_codes()`.
- New `GET /payroll/off-cycle/employee-options?company_id=` → renders `templates/payroll/_employee_options.html`, reusing `_off_cycle_employees()`.

Both are read routes: router-level `get_current_user` plus `assert_company_access` on the submitted `company_id`, so they cannot be used to enumerate another tenant's employees.

**b. Distinguish "wrong company" from "no access".** In `create_off_cycle` (`routers/pay_periods.py`), the existing `assert_company_access(current_user, company_id, db)` must stay a **404** — that is the tenancy boundary. But the separate check that the employee belongs to the submitted company is a different situation: both records are ones this user may legitimately see, and the mismatch is an ordinary form mistake. Change that branch from

```python
if employee.company_id != company_id:
    raise HTTPException(status_code=404, detail="Employee not found")
```

to a 422 re-render of `payroll/off_cycle.html` with `errors["employee_id"] = "That employee belongs to a different company."`

Keep the 404 whenever `get_scoped_employee` itself fails — that is an out-of-scope employee and must stay indistinguishable from a missing one. The distinction is the point: *out of scope* → 404; *in scope but mismatched* → 422. Apply the same reasoning to `save_timesheet_row`, which has the identical shape.

---

## 3. `user_companies` re-read 2–4× per request; switcher opens its own session

**Severity: Medium** — pure waste on every authenticated page view.

`accessible_company_ids()` queries `user_companies` on every call, and a single request calls it several times via `accessible_companies`, `scope_query`, `assert_company_access` and the scoped loaders. Separately, `company_context()` in `main.py` opens its **own** `SessionLocal()` on every page render, because `layout.html` calls it for the nav switcher.

**Measured** (SELECT counts per request, preparer with two companies):

| Path | total SELECTs | `user_companies` reads |
|---|---|---|
| `/` | 8 | 2 |
| `/employees/` | 9 | 3 |
| `/payroll/` | 9 | 3 |
| `/reports/tax-liability?company_id=-1&year=2026` | 11 | 4 |

### Fix

**a. Cache per request.** Memoise the resolved ids on `request.state` inside `accessible_company_ids`. The scope helpers currently take `(user, db)` and have no `Request`; the least invasive route is a small cache keyed by user id held on the request, which means threading `request` into `utils/company_scope.py`. Prefer instead caching on the **`User` instance** — `get_current_user` returns one object per request, so a private attribute on it is naturally request-scoped and needs no signature changes:

```python
def accessible_company_ids(user, db):
    cached = getattr(user, "_company_ids_cache", None)
    if cached is not None:
        return cached
    ...
    user._company_ids_cache = result
    return result
```

Correctness note: the cache must **not** outlive the request. It won't — `get_current_user` re-queries the `User` per request — but say so in a comment, because a stale cache here would re-open the revocation hole that §2 of the main plan deliberately closed. `tests/test_multi_company.py::test_revoked_access_takes_effect_without_relogin` already guards it.

**b. Stop opening a second session for the switcher.** Have `get_active_company` stash `{"active": ..., "available": [...]}` on `request.state`, and have `company_context()` read that, falling back to its current self-contained query only when the key is absent (a route that has no `ActiveCompany` dependency). Saves one connection and two queries on most pages.

**Verification:** assert the measured counts drop (a test that fails if `user_companies` is read more than once per request is worth having — it pins the regression).

---

## 4. `user_companies` audit rows carry the wrong `record_id`

**Severity: Medium** — the audit trail for a security boundary points at the wrong row.

`AuditLog.record_id` means "the primary key of the row in `table_name`" (`models/audit.py:13`). `_sync_company_assignments` in `routers/users.py` logs `table_name="user_companies"` but passes `target_user.id` — the `users` PK. Any `(table_name, record_id)` lookup against those rows resolves to the wrong record, or to nothing.

### Fix

Log the real `user_companies` PK:

- **Insert:** `db.add(...)` then `db.flush()` to populate `row.id`, then `log_change(db, "user_companies", row.id, "insert", ...)`.
- **Delete:** capture the row ids before deleting (the current code already queries the existing set — have it select rows rather than just ids), then log one entry per captured id.

Keep `new_values`/`old_values` carrying `{"user_id": ..., "company_id": ...}` so an entry is readable without a join even after the row is gone.

Simpler alternative if the flush is unwelcome: log under `table_name="users"` with `record_id=target_user.id` and a `{"company_access_granted": id}` payload. That is self-consistent and puts access changes next to the role changes already logged under `users`. Either is defensible; the first is more faithful to the column's meaning and is the recommendation.

---

## 5. Consolidated payroll register lists indistinguishable periods

**Severity: Low.**

With `company_id=-1` the register widens its Pay Period dropdown across every accessible company, but the option label is only `{{ pp.pay_date }} ({{ pp.start_date }} – {{ pp.end_date }})` (`templates/reports/payroll_register.html:44-45`). Companies on the same pay calendar produce byte-identical options, so the user cannot tell which client they are selecting.

The register is inherently single-period, so unlike the other five consolidated reports it has no `groups` to render — widening the dropdown is the whole feature, which makes the ambiguity the entire problem.

### Fix

Prefix the option label with the company name when `consolidated` is set. `payroll_register` already passes `joinedload(PayPeriod.company)`, so the data is loaded:

```jinja
<option value="{{ pp.id }}" ...>
  {% if consolidated %}{{ pp.company.name }} — {% endif %}{{ pp.pay_date }} ({{ pp.start_date }} – {{ pp.end_date }})
</option>
```

---

## 6. `tax_liability` computes every row twice when consolidated

**Severity: Low.**

`routers/reports.py` calls `_tax_liability_rows(db, paychecks)` once for the flat `rows`/`yearly`, then again per company inside the `CONSOLIDATED` branch. Each call issues its own `PayPeriod` lookup, so an N-company run does N+1 period queries and duplicates all the aggregation.

### Fix

Compute the per-company groups first, then derive the flat view from them — `rows` as the concatenation and `yearly` as the sum of the group totals — instead of aggregating the whole set a second time. `_totals()` already exists and takes the key list, so the grand total is `_totals([g["totals"] for g in groups], _TAX_LIABILITY_KEYS)` over the per-group dicts.

Apply the same shape to `workers_comp`, `deductions` and `client_liabilities`, which have the identical double-pass structure but are cheaper because their row builders issue no extra queries.

---

## 7. `test_no_beta_data_in_response_bodies` passes vacuously

**Severity: Low** — a security test that cannot fail for the right reason.

The test asserts Beta's data is absent from responses that are, by the preceding test, all 404s with essentially empty bodies. It therefore cannot distinguish "scoping worked" from "the route 404s for some unrelated reason" — a renamed route would keep it green.

### Fix

Give it a positive control. For each path, assert both directions against the same fixture data:

1. As the **owning** company's user, the equivalent path returns 200 **and contains** the marker string. This proves the marker would appear if scoping failed.
2. As the other company's user, the path 404s and omits it.

Without step 1 the assertion has no power. `test_every_cross_company_read_is_404` remains the real guard; this test should become the "and the data really was reachable" complement rather than a second weak restatement of it.

---

## 8. Inactive users get no company assignments on upgrade

**Severity: Decide & document** — a deliberate choice that is currently undocumented outside the migration body.

The backfill filters `WHERE u.role != 'admin' AND u.is_active = 1`. A deactivated non-admin gets no `user_companies` rows, so reactivating that account later grants access to nothing. The only signal is the amber "None" in the Companies column of `/users/`.

### Options

1. **Keep and document (recommended).** Reactivating a dormant account *should* require a deliberate re-grant — that is the safer default for an app holding SSNs and bank details, and it matches the principle that access is granted explicitly. Document it in `CLAUDE.md` next to the existing multi-company notes, and surface it in the UI: when editing an inactive non-admin with zero companies, show "This user has no company access; assign companies before reactivating."
2. Backfill inactive users too — restores exact pre-migration behaviour on reactivation, at the cost of silently granting access to accounts nobody reviewed.
3. Block reactivation of a non-admin with zero companies. Rejected: too blunt, and parking an account without access is legitimate.

Recommendation is option 1. The decision is already recorded in the project memory note; this plan is where the reasoning should live.

---

## Suggested order

1. **#1** first and alone — it is the only data-corrupting defect, and its fix is confined to the migration plus a new round-trip test.
2. **#4** next — audit integrity, small and self-contained.
3. **#2** — the largest chunk (two new partial routes plus templates), and the only one users feel directly.
4. **#3** — measurable, low risk, but touches the scope module that everything else depends on, so land it after the behaviour is settled.
5. **#5, #6, #7, #8** — small cleanups, batchable into one change.

## Critical files

- `alembic/versions/b7f2a91c40d3_multi_company_scoping.py` — #1
- `routers/users.py` — #4
- `routers/pay_periods.py`, `routers/employees.py`, `templates/employees/form.html`, `templates/payroll/off_cycle.html`, new `_wc_options.html` / `_employee_options.html` — #2
- `utils/company_scope.py`, `main.py`, `routers/auth.py` — #3
- `templates/reports/payroll_register.html` — #5
- `routers/reports.py` — #6
- `tests/test_multi_company.py` — #7
- `CLAUDE.md`, `templates/users/form.html` — #8

## Verification

1. `python -m pytest` — full suite green, including the new migration round-trip test (#1) and the per-request query-count test (#3).
2. Round-trip: `upgrade → downgrade → upgrade` three times against a seeded DB with a shared WC code; the code count must return to and stay at its post-first-upgrade value, and every employee must still resolve to a code at an unchanged rate.
3. Manual, two companies: on `/payroll/off-cycle/new` change the company select and confirm the employee list refreshes; submit a deliberate mismatch and confirm a field error rather than a 404. Confirm an out-of-scope `company_id` still 404s.
4. Manual: consolidated payroll register shows company names in the period dropdown.

## Explicitly out of scope

- Re-opening the 404-vs-403 convention, per-company roles, or admin-bypasses-scope — all settled in `plans/MULTI-COMPANY-PLAN.md`.
- Consolidation for 941 / W-2 / OK withholding. Still per-EIN, still refused.
- The remaining unbuilt features in `plans/PLAN.md` Open Questions (ACH, email pay stubs, PTO accrual, 1099, multi-state).
