# RBAC Plan: 4-Role System (admin / preparer / approver / read_only)

> Status: **Implemented.** `CLAUDE.md`'s Auth & CSRF section has been updated per §8. This document remains the reference for the design rationale.

## Context

The app currently has a binary auth gate: every mutating route requires `role == "admin"` via `require_admin` (`routers/auth.py:34`). `models/user.py` already declares `USER_ROLES = ["admin", "read_only"]`, but `read_only` is unreachable in practice — there is no way to create a second user account at all. `main.py` seeds exactly one admin on first run and no user-management UI exists.

Because every account is admin-or-nothing, the same user both prepares payroll data (timesheets, employee edits, draft calculation) and approves/releases it (approve run, void checks, mark paid). That's the standard payroll fraud-control gap: no separation of duties between who enters the numbers and who releases the money.

This plan adds `preparer` and `approver` roles, makes `read_only` actually usable, and adds the user-management screen needed to assign roles in the first place.

**Decisions locked in with the user:**
- 4 roles: `admin`, `preparer`, `approver`, `read_only`
- Role-level split only — no per-run self-approval tracking (e.g. blocking the same user who calculated a draft from approving it). Simpler; relies on assigning preparer/approver to different people.
- Full CRUD user-management UI (not a minimal create/deactivate-only stub).

## Role scope

| Role | Can do | Cannot do |
|---|---|---|
| **admin** | Everything below, plus company/benefit/WC-code config, user management | — |
| **preparer** | Add/edit employees, W-4 & OK withholding elections, benefit enrollments, garnishments, open pay periods, enter timesheets, calculate draft payroll | Approve/void/mark-paid a run, company config, user management |
| **approver** | Approve payroll runs, void paychecks, mark periods paid | Data entry (employees, timesheets, draft calc), company config, user management |
| **read_only** | View everything (employee records, pay periods, all reports) | Any POST/mutating action anywhere |

Company/benefit-plan/workers-comp-code configuration stays **admin-only**, not preparer-accessible — it's tenant-level setup that structurally affects every future payroll run, a different risk class than routine data entry.

## Implementation approach

### 1. Auth layer — `routers/auth.py`

Replace `require_admin` with a factory so "admin implies every role" lives in one place:

```python
def require_role(*allowed_roles: str):
    def _dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role == "admin" or current_user.role in allowed_roles:
            return current_user
        raise HTTPException(status_code=403, detail=f"Requires role: {', '.join(allowed_roles)}")
    return _dependency

require_admin = require_role("admin")
require_preparer = require_role("preparer")
require_approver = require_role("approver")

AdminUser = Annotated[User, Depends(require_admin)]
PreparerUser = Annotated[User, Depends(require_preparer)]
ApproverUser = Annotated[User, Depends(require_approver)]
```

Each `require_role(...)` call happens once at module scope, so `require_preparer`/`require_approver` are stable callables — required for `app.dependency_overrides` in tests. `require_admin`'s external behavior is unchanged (admin-only). `read_only` needs no new dependency — it already only satisfies the base `get_current_user` router-level dependency, so it keeps view-only access everywhere without any change.

### 2. `models/user.py`

```python
USER_ROLES = ["admin", "preparer", "approver", "read_only"]
```

No hierarchy helper added here — the admin-implies-all logic lives solely in `require_role` (§1), so there's one source of truth.

### 3. Route reassignment

- **`routers/employees.py`** — all 8 current `AdminUser` params (`employees.py:82,223,314,363,393,419,459,497`) → `PreparerUser`. Routine payroll data entry.
- **`routers/pay_periods.py`** — split:
  - `PreparerUser`: `create_pay_period` (`:63`), `create_off_cycle` (`:133`), `save_timesheet_row` (`:460`), `calculate_draft` (`:516`)
  - `ApproverUser`: `void_check` (`:251`), `approve_period` (`:540`), `mark_paid_period` (`:573`)
- **`routers/companies.py`** — **no change**, stays `AdminUser` at all 7 sites (company/WC-code/benefit-plan config).
- **`routers/reports.py`** — no change; already gated only by base `get_current_user`, so `read_only` can already view/export everything.

### 4. New user-management feature (admin-only)

New `routers/users.py`, `prefix="/users"`, router-level `dependencies=[Depends(get_current_user)]` plus per-route `current_user: AdminUser` — matches the existing per-route admin-gating convention (also gives each handler a user for `log_change`'s `changed_by`). No Pydantic schemas — `schemas/` is an empty placeholder package; follow the existing plain-`Form(...)` + hand-rolled `errors: dict` pattern used in `companies.py:37-63` / `employees.py:79-128`.

Routes:
- `GET /users/` — list (username, role, is_active, created_at) → `templates/users/list.html`
- `GET /users/new`, `POST /users/new` — create (username, password, role); validate username unique, role in `USER_ROLES`, password min length. `hashed_password=hash_password(password)` (reuse from `routers.auth`). `log_change(db, "users", user.id, "insert", ...)`.
- `GET /users/{id}/edit`, `POST /users/{id}/edit` — change role / `is_active`. Lockout guard applies (below).
- `GET /users/{id}/reset-password`, `POST /users/{id}/reset-password` — admin sets a new password directly for another user (no email flow exists anywhere in this app). Never log the plaintext or hash value.
- No delete route — deactivate only, per approved scope.

**Lockout-prevention guard** (helper in `routers/users.py`):

```python
def _active_admin_count(db, exclude_user_id=None) -> int:
    q = db.query(User).filter(User.role == "admin", User.is_active.is_(True))
    if exclude_user_id is not None:
        q = q.filter(User.id != exclude_user_id)
    return q.count()
```

In `POST /users/{id}/edit`: if the target is currently an active admin and the edit would demote or deactivate them, and `_active_admin_count(db, exclude_user_id=id) == 0`, reject with a form error (HTTP 422) and do not commit. Applies uniformly whether an admin is editing their own account or someone else's.

Nav: add a `Users` link in `templates/layout.html` sidebar (near "Companies"), gated `{% if has_role(request, 'admin') %}`.

### 5. Template role-awareness

Generalize the `is_admin` global in `main.py:64-68` without breaking existing callers:

```python
def has_role(request, *roles):
    return request.session.get("role") in roles or request.session.get("role") == "admin"

def is_admin(request):
    return has_role(request, "admin")
```

Update button-visibility gates (UX only — the router dependency is the real security boundary):
- `templates/employees/list.html:8`, `templates/employees/profile.html:26`, `templates/payroll/list.html:8` → `{% if has_role(request, 'preparer') %}`
- `templates/companies/detail.html:14` → unchanged, stays `is_admin(request)`
- `templates/payroll/detail.html` (Calculate / Approve / Mark-Paid / Void forms, currently ungated) and `templates/payroll/_timesheet_row.html`: gate Calculate + timesheet-save with `has_role(request, 'preparer')`; gate Approve/Mark-Paid/Void with `has_role(request, 'approver')`.

### 6. Migration

**No new Alembic revision.** No CHECK constraint exists today even for the current 2-value role column (`String(20)`, no `CheckConstraint`), and the only writers of `User.role` are `main.py`'s seed and the new `routers/users.py` (which validates `role in USER_ROLES` before every write). Adding SQLite CHECK-constraint support would require a batch/rebuild migration for a guard already fully enforced at the application boundary — skip it, consistent with the existing no-roles-table design. Revisit only if the team wants belt-and-suspenders DB enforcement later.

### 7. Tests

- `tests/conftest.py`'s `client` fixture: add `require_preparer`/`require_approver` overrides (same fake admin — admin satisfies every role check) alongside the existing `require_admin` override, plus a `has_role` template-global override (`lambda request, *roles: True`) alongside the existing `is_admin` override.
- `tests/test_auth.py`'s `TestRoleEnforcement`: add `preparer_user`/`approver_user` fixtures (same pattern as existing `admin_user`/`readonly_user`), and a route-level matrix — preparer can POST to employees but not approve; approver can approve but not POST to employees; read_only and each wrong role get 403 on both; admin passes everywhere; a preparer hitting `POST /companies/new` still gets 403.
- New `tests/test_roles.py` — direct unit tests of `require_role`/`require_admin`/`require_preparer`/`require_approver` against `User(role=...)` instances, no HTTP.
- New `tests/test_users.py` — CRUD via `client` fixture (create/edit-role/deactivate/reset-password persist correctly, `log_change` rows written, password never stored plaintext); access-control via `auth_client` + role fixtures (only admin can reach any `/users/*` route); lockout test (single active admin can't self-demote/deactivate; with 2 admins it succeeds).

### 8. CLAUDE.md follow-up

After this ships, update the `### Auth & CSRF` section of `CLAUDE.md`:
- Describe `require_role`/`require_admin`/`require_preparer`/`require_approver` and the 4 roles.
- Mention `has_role(request, *roles)` alongside `is_admin(request)`.
- Note the `client` test fixture now also overrides `require_preparer`/`require_approver`.
- Record the "companies stay admin-only" decision so it isn't "fixed" by mistake later.

## Critical files

- `routers/auth.py` — role dependency factory
- `models/user.py` — `USER_ROLES`
- `routers/employees.py`, `routers/pay_periods.py` — route reassignment
- `routers/users.py` — new, user management
- `main.py` — `has_role` global, register new router
- `templates/layout.html`, new `templates/users/*.html`
- `tests/conftest.py`, `tests/test_auth.py` — new fixtures/overrides

## Verification

1. `python -m pytest` — full suite green, including new `tests/test_roles.py` and `tests/test_users.py`.
2. `python -m pytest tests/test_auth.py::TestRoleEnforcement -v` — role matrix passes.
3. Manual: `uvicorn main:app --reload`, log in as seeded admin, create one user per role via `/users/new`, log in as each and confirm: preparer can add an employee but gets 403 approving a run; approver can approve/void but gets 403 adding an employee; read_only sees pages but no action buttons and gets 403 on any POST; admin unrestricted.
4. Lockout check: as the sole admin, try demoting/deactivating yourself via `/users/{id}/edit` → rejected with a form error.

## Explicitly out of scope (for now)

- Per-run self-approval blocking (tracking who prepared a specific run and rejecting approval by that same user even if they hold the approver role)
- A `manager` role scoped to a department/subset of employees
- DB-level CHECK constraint on `users.role`
