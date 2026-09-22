# Multi-Company Plan: Active-Company Context + Per-User Tenant Scoping

> Status: **Implemented.** `CLAUDE.md` gained a "Multi-company scoping" section per §10. This document remains the reference for the design rationale.
>
> Deviations from the plan as written, all discovered during implementation:
> - Extra holes found and closed beyond the 21 listed lookups: `create_w4`, `create_ok_withholding` and `enroll_benefit` never verified the employee existed at all; `enroll_benefit` allowed enrolling into another company's benefit plan; `create_off_cycle` allowed paying one company's employee out of another's pay period; `save_timesheet_row` allowed booking hours across companies.
> - Employee list filters were submitting `status_filter`/`company_filter` while the route read `status`/`company_id`, so neither filter had ever worked. Fixed, since the company filter now matters.
> - Report `company_id` uses `-1` (not a separate flag) for "all my companies", keeping `0` as the existing unset sentinel.
>
> Defects found *after* this shipped — migration round-trip duplicates WC codes, stale dependent dropdowns, repeated scope queries, and others — are catalogued with reproductions in `plans/MULTI-COMPANY-FOLLOWUP-PLAN.md`, which is now also Implemented. None were tenancy holes.

## Context

The schema is already multi-tenant. `companies` exists, and `employees.company_id` (`models/employee.py:24`), `pay_periods.company_id` (`models/payroll.py:32`), `client_liabilities.company_id` (`models/payroll.py:121`) and `benefit_plans.company_id` (`models/benefit.py:24`) are all non-nullable FKs, indexed. Nothing in the data model needs to change to *store* multiple companies — the app can hold them today.

What's missing is everything above the schema:

1. **No active-company context.** Multi-company is expressed as an optional filter dropdown on each list page (`routers/employees.py:43-44`, `routers/pay_periods.py:36-37`) that defaults to "all companies", and a mandatory company picker on every create form. A user running payroll for one client re-picks that client on every page and every form, and a mis-pick silently files an employee or a pay period under the wrong company.

2. **No user↔company access control.** Every authenticated user sees every company. `get_current_user` (`routers/auth.py:24`) is the only tenant-relevant gate and it is tenant-blind. For a single business this is fine; for a bookkeeper or PEO running payroll for several unrelated clients it means any preparer account can read every client's SSNs, wages, and bank data. The 4-role RBAC system (`plans/RBAC-PLAN.md`) controls *what* a user may do, and this plan adds the orthogonal *which companies* they may do it to.

3. **Workers comp codes are global but presented as per-company — a live data bug.** `WorkersCompCode` (`models/workers_comp.py:8-14`) has no `company_id`, yet the UI serves it under `/companies/{company_id}/wc-codes` (`routers/companies.py:288`) and `create_wc_code` (`routers/companies.py:148`) ignores its own `company_id` path param when inserting. Every employee form lists all codes unfiltered (`routers/employees.py:67,119,208,255`). Editing an NCCI rate while "inside" Company A changes the employer workers-comp cost of every other company's next payroll run, via `services/payroll_service.py:371-372`. This is the one genuine schema gap and it must be closed here.

**Decisions locked in with the user:**
- Do **both** the UX switcher and real per-user tenant enforcement — not one or the other.
- **Global role.** `users.role` stays a single role applied across all of a user's companies. A preparer is a preparer everywhere they have access. `require_role` is untouched; company access is a separate, orthogonal check.
- **Consolidated reporting for non-filing reports only.** Tax-filing reports stay strictly single-company.

## Design

### 1. Data model

**New association table** — `models/user_company.py`:

```python
from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base


class UserCompany(Base):
    __tablename__ = "user_companies"
    __table_args__ = (UniqueConstraint("user_id", "company_id", name="uq_user_company"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
```

A plain model rather than a bare `Table`, to match the rest of `models/` and to give the user-management UI something ordinary to query. No `role` column — per the locked-in global-role decision. Export it from `models/__init__.py`.

**Admin bypasses company scoping**, exactly as admin bypasses every role check in `require_role` (`routers/auth.py:37`). One mental model: *admin passes everything.* Admin accounts need no `user_companies` rows and implicitly see all companies. This keeps the firm owner from having to re-grant themselves access every time a client is onboarded.

**`WorkersCompCode` gains `company_id`** (`models/workers_comp.py`):

```python
company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
```

Non-nullable, matching every other tenant-scoped table. Backfill strategy in §8.

### 2. Active company (session)

Mirror the existing session convention in `routers/auth.py:100-102` (`user_id`, `username`, `role`) with a fourth key, `company_id`.

New dependency in `routers/auth.py` alongside the role dependencies:

```python
def get_active_company(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Optional[Company]:
    """Resolve the session's active company, falling back to the user's first."""
    allowed = accessible_company_ids(current_user, db)   # see §3
    company_id = request.session.get("company_id")
    if company_id is not None and (allowed is ALL or company_id in allowed):
        company = db.query(Company).filter(Company.id == company_id).first()
        if company:
            return company
    company = _first_accessible_company(db, allowed)
    request.session["company_id"] = company.id if company else None
    return company

ActiveCompany = Annotated[Optional[Company], Depends(get_active_company)]
```

Resolution order: valid session value → user's first accessible company by name → `None`. It returns `Optional` because two states legitimately have no active company: a fresh install with zero companies, and a non-admin with zero assignments (§3). Re-validating the session value against current access on every request matters — access revoked by an admin must take effect without waiting for the user to log out.

**Switch route** — `POST /companies/switch` in `routers/companies.py`, taking `company_id: int = Form(...)`, `_csrf: CsrfProtect`, and `current_user: CurrentUser` (not `AdminUser` — every role switches companies). Validates access, sets `request.session["company_id"]`, redirects to the `Referer` path if it is app-local or `/` otherwise. POST + CSRF rather than a convenient `GET /companies/switch/{id}`, because it mutates session state and every other state change in this app already goes through the CSRF dependency; a GET would be the one exception.

**Switcher UI** — a `<select>` in the `templates/layout.html` top bar (`layout.html:95-106`, left of the username), auto-submitting its form on change. Rendered from a new `active_company` / `available_companies` pair injected by a Jinja2 global (§7) so no route has to pass them. Hidden entirely when the user has access to fewer than two companies — a single-company install should look exactly like it does today.

### 3. Access enforcement

New module `utils/company_scope.py`, so the logic has one home and `routers/auth.py` does not grow a second concern:

```python
ALL = object()   # sentinel: unrestricted (admin)


def accessible_company_ids(user: User, db: Session):
    """Return ALL for admins, else the list of company ids assigned to the user."""
    if user.role == "admin":
        return ALL
    return [
        row.company_id
        for row in db.query(UserCompany).filter(UserCompany.user_id == user.id).all()
    ]


def scope_query(query, column, user: User, db: Session):
    """Apply a company filter to a query unless the user is unrestricted."""
    allowed = accessible_company_ids(user, db)
    if allowed is ALL:
        return query
    return query.filter(column.in_(allowed))


def assert_company_access(user: User, company_id: int, db: Session) -> None:
    allowed = accessible_company_ids(user, db)
    if allowed is not ALL and company_id not in allowed:
        raise HTTPException(status_code=404, detail="Not found")
```

**404, not 403, on out-of-scope access.** A 403 confirms that the requested employee or pay period exists and belongs to someone else; across unrelated payroll clients that is itself a disclosure. Out-of-scope records should be indistinguishable from nonexistent ones. This deliberately differs from `require_role`'s 403 (`routers/auth.py:39`) — a role failure reveals nothing about other tenants' data, a scope failure does.

**The 21 bare-ID lookups are the enforcement surface.** Every route that resolves a record from a path parameter without joining to a company is currently a cross-tenant read the moment assignments exist:

| File | Lines | Entity |
|---|---|---|
| `routers/employees.py` | 178, 204, 249, 301, 350, 446, 473 | `Employee` |
| `routers/pay_periods.py` | 186, 232, 257, 285, 335, 425, 472, 476, 524, 548, 581 | `Employee` / `Paycheck` / `PayPeriod` |
| `routers/companies.py` | 311, 332 | `WorkersCompCode` |
| `routers/reports.py` | 112 | `PayPeriod` |

Rather than sprinkling `assert_company_access` at 21 call sites, add scoped loader helpers to `utils/company_scope.py` and replace the lookups:

```python
def get_scoped_employee(db, user, employee_id, *options) -> Employee
def get_scoped_pay_period(db, user, period_id, *options) -> PayPeriod
def get_scoped_paycheck(db, user, paycheck_id, *options) -> Paycheck
def get_scoped_wc_code(db, user, code_id) -> WorkersCompCode
```

Each applies the caller's existing `joinedload` options, filters on the entity's company (joining `PayPeriod` for `Paycheck`, which has no direct `company_id`), and raises 404 when missing *or* out of scope — collapsing the current "if not X: raise 404" blocks into one call. Every one of these routes must therefore gain a `current_user` parameter; the read routes currently have none, since they rely on the router-level `get_current_user` dependency.

**Cross-company writes must be validated too**, not just reads. `create_employee` (`routers/employees.py:80`) and `create_pay_period` / `create_off_cycle` (`routers/pay_periods.py:61,131`) accept `company_id: int = Form(...)` straight from the client — call `assert_company_access` before constructing the row. Same for `update_employee`'s reassignment at `routers/employees.py:266`, which can move an employee *into* a company the user cannot see.

**Zero-company state.** A non-admin with no assignments gets empty lists and an explanatory empty state, never a crash or a traceback. Worth an explicit test.

### 4. List routes

Each list route keeps its existing optional `company_id` filter param but changes default behavior: no explicit filter now means *the active company*, not *all companies*, and the dropdown is populated only with accessible companies.

- `routers/employees.py:32-58` — default to active company; `companies` (`:46`) becomes scoped.
- `routers/pay_periods.py:33-43` — same.
- `routers/companies.py:19-20` — `list_companies` returns only accessible companies (admin still sees all).
- Every create form's company picker (`routers/employees.py:66,118,254`, `routers/pay_periods.py:50,81,113,150`) is scoped and pre-selects the active company.
- **WC code lists** (`routers/employees.py:67,119,208,255`) filter by the employee's company — the bug from §Context item 3.

An explicit "All my companies" option stays available on list pages; it is the default that changes.

### 5. Reports

`_load_paychecks` (`routers/reports.py:48`) changes signature from `company_id: int` to `company_ids: list[int]`, filtering `PayPeriod.company_id.in_(company_ids)`. All ten report routes pass a list.

**Per-EIN filing reports — single company, required:**
- `quarterly_941` (`:236`), `w2_export` (`:423`), `ok_withholding` (`:360`)

These are filed per EIN. Consolidating them across companies would produce a return that reconciles to no real filing. They must reject a consolidated request with a form-level error rather than silently summing — `company_id=0` is currently the "unset" sentinel on these routes and must stay unset-means-prompt, never unset-means-all.

**Consolidated option allowed:**
- `payroll_register` (`:90`), `tax_liability` (`:143`), `workers_comp` (`:293`), `deductions_report` (`:504`), `client_liabilities_report` (`:555`), `new_hires_report` (`:613`)

These gain an "All my companies" choice in the existing company dropdown. Templates group rows by company with per-company subtotals plus a grand total; a consolidated run must not present a single undifferentiated total, which would be indistinguishable from one company's figures. `tax_liability` is in this group because it is an internal cash-planning view, not a filed return — note in the template that deposit *schedules* are still determined per EIN.

Every report route also gains `current_user` and scopes its company dropdown; `pay_period_id` (`routers/reports.py:112`) is resolved through `get_scoped_pay_period`.

### 6. User management

`routers/users.py` gains company assignment:
- `GET /users/` — list gains a "Companies" column: "All" for admins, else a count or comma-separated names.
- `GET|POST /users/{id}/edit` — a multi-select (checkbox list) of all companies. Diff the submitted set against existing `UserCompany` rows: delete removed, insert added. Suppress the control with an "Admins have access to all companies" note when the target's role is `admin`.
- `POST /users/new` — same control, so a user can be created already scoped.
- `log_change(db, "user_companies", ...)` on grant and revoke. Company access is a security boundary and belongs in the audit log next to role changes.

**Guard:** creating or editing a **non-admin** user with zero companies is allowed but warned about in the UI ("This user will not see any company data"), not blocked — it is a legitimate way to park an account without deactivating it.

### 7. Templates

Add a Jinja2 global in `main.py`, next to `has_role` / `is_admin` (`main.py:65-74`):

```python
def company_context(request):
    """Returns {"active": Company|None, "available": [Company, ...]} for the nav switcher."""
```

It opens its own short-lived `SessionLocal()` exactly as the dashboard does (`main.py:91-100`), so no route needs to pass switcher data into its template context.

- `templates/layout.html:95-106` — switcher `<select>` in the top bar, hidden when fewer than two companies are accessible.
- Company pickers on create/edit forms pre-select the active company.
- `templates/users/*.html` — the company assignment control.
- Report templates for the six consolidated reports — per-company grouping and subtotals.
- `main.py:86-107` dashboard — scope `company_count`, `employee_count` and `open_pay_runs` to the active company (or to all accessible companies), and surface which company the numbers describe. Today they are global counts, which under tenant scoping would leak the size of other clients.

### 8. Migration

**A real Alembic revision is required** — unlike `plans/RBAC-PLAN.md` §6, this adds a table and a non-nullable column, and existing rows need backfill.

```bash
alembic revision --autogenerate -m "multi-company: user_companies, wc code company scoping"
```

Hand-edit the generated revision; autogenerate will not produce the backfill or the SQLite-safe column add.

1. **Create `user_companies`.**
2. **Backfill assignments:** grant every existing **non-admin** active user access to every existing company. This preserves today's behavior exactly — nobody loses access at deploy time. Admins need no rows (§1). New restrictions then become a deliberate admin action rather than a surprise lockout on upgrade.
3. **Add `workers_comp_codes.company_id`** via `op.batch_alter_table` — SQLite cannot `ALTER TABLE ADD COLUMN` with a NOT NULL constraint and an FK in one step, so add nullable, backfill, then set non-nullable inside the batch context.
4. **Backfill WC codes** — the subtle part, since codes are currently shared:
   - For each existing code, find the distinct companies of the employees referencing it (`employees.workers_comp_code_id`).
   - Referenced by exactly one company → set `company_id` to it.
   - Referenced by several → keep the original row for the first company and **clone** it per additional company, repointing those companies' employees at their clone. Rates and descriptions are preserved, so no payroll figure changes.
   - Referenced by none → clone to every company, so each company's picker keeps the full catalog it sees today.
   - Zero companies exist → delete orphan codes (nothing can reference them).

   Cloning rather than assigning-to-one is what keeps already-approved historical paychecks reconcilable: every employee keeps a code with an identical rate, so re-running any report over past periods reproduces the same numbers.
5. `alembic upgrade head`.

### 9. Tests

- **`tests/conftest.py`** — `client` fixture (which bypasses auth) needs `get_active_company` overridden to return the existing `company` fixture, and `company_context` stubbed, or every template render breaks. Add a `second_company` fixture plus employees/pay periods under it — most scoping tests need two tenants to be meaningful. Add a `scoped_user` fixture: a preparer assigned to exactly one company.
- **New `tests/test_company_scope.py`** — unit tests of `accessible_company_ids` (admin → `ALL`, assigned user → list, unassigned → `[]`), `scope_query`, and `assert_company_access`.
- **New `tests/test_multi_company.py`** via `auth_client`, the real-auth fixture:
  - **The IDOR matrix — the core of this plan.** For each of the 21 hardened routes, a user scoped to Company A requesting a Company B record gets **404**, and the response body contains no Company B data. Table-driven over (path template, entity fixture).
  - Cross-company **write** rejection: `POST /employees/new` with another company's `company_id`; `POST /employees/{id}/edit` reassigning into an inaccessible company; `POST /payroll/periods/new` likewise.
  - Switcher: switching to an accessible company sets the session and changes list contents; switching to an inaccessible one is rejected and leaves the session untouched.
  - Session re-validation: revoke access while a session holds that `company_id` → next request silently falls back, does not 500 and does not serve the revoked company.
  - Zero-company user: every list page renders 200 with an empty state.
  - Admin: sees both companies everywhere, with no `user_companies` rows at all.
- **`tests/test_reports.py`** — filing reports reject a consolidated request; the six consolidated reports return correct per-company subtotals and grand totals across two companies; report company dropdowns contain only accessible companies.
- **`tests/test_companies.py`** — WC codes created under Company A do not appear in Company B's lists or employee-form pickers.
- **`tests/test_users.py`** — assignment CRUD, `log_change` rows written on grant/revoke, admin edit form suppresses the control.

### 10. CLAUDE.md follow-up

After this ships, update `CLAUDE.md`:
- New **Multi-company scoping** section: `user_companies`, admin-bypasses-scope, `utils/company_scope.py`, the scoped-loader helpers, and the **404-not-403** convention with its reasoning.
- Auth & CSRF section: `get_active_company` / `ActiveCompany`, `session["company_id"]`, and that company scope is orthogonal to the 4 roles.
- Note that `client` now also overrides `get_active_company` and `company_context`.
- Reports section: `_load_paychecks` now takes `company_ids: list[int]`; which reports may consolidate and which may not, and why.
- Record that WC codes are per-company as of this change.

## Critical files

- `models/user_company.py` — new
- `models/workers_comp.py` — `company_id`
- `utils/company_scope.py` — new; scope helpers and scoped loaders
- `routers/auth.py` — `get_active_company`, `ActiveCompany`
- `routers/employees.py`, `routers/pay_periods.py`, `routers/companies.py`, `routers/reports.py` — scoped lookups, scoped lists, switch route
- `routers/users.py` — assignment UI
- `main.py` — `company_context` global, scoped dashboard counts
- `templates/layout.html` — switcher
- `alembic/versions/*` — new revision with backfill
- `tests/conftest.py`, `tests/test_multi_company.py`, `tests/test_company_scope.py`

## Verification

1. `python -m pytest` — full suite green, including the new scope and multi-company modules.
2. `python -m pytest tests/test_multi_company.py -v` — IDOR matrix passes.
3. Manual, two companies seeded with employees in each:
   - Admin sees both, switches freely, dashboard counts follow the switcher.
   - A preparer assigned only to Company A sees only A in every dropdown; hand-editing a URL to a Company B employee, paycheck, pay period or paystub PDF returns 404.
   - WC code added under Company A does not appear in Company B's employee form.
   - 941 and W-2 refuse a consolidated run; payroll register offers "All my companies" and shows per-company subtotals.
   - Revoke the preparer's Company A access while they are logged in → their next page load does not show A's data.
4. Upgrade check against a copy of an existing `payroll.db`: `alembic upgrade head`, then confirm every pre-existing employee still resolves to a WC code with an unchanged rate, and that a payroll register run over a historical period reports the same totals as before the migration.

## Explicitly out of scope (for now)

- **Per-company roles** — preparer at one client, approver at another. Decided against; `users.role` stays global. Revisit only with a concrete need, since it makes every role check company-aware.
- **Company-scoped audit log views** — `audit_log` rows are not company-tagged; scoping them is its own change.
- **Per-company branding** on paystub PDFs beyond the company name already rendered.
- **Cross-company employee transfer** with history — today `update_employee` repoints `company_id` and prior paychecks stay attached to the old company via their pay period. Adequate, but not a designed transfer flow.
- **Company archive/soft-delete** — no delete route exists for companies at all today.
- **Row-level DB enforcement** (e.g. SQLite views or triggers). Scoping is enforced at the application boundary, consistent with how roles are enforced.
