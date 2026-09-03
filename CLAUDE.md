# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run all tests
python -m pytest

# Run a single test file
python -m pytest tests/test_auth.py

# Run a single test by name
python -m pytest tests/test_auth.py::TestLoginLogout::test_login_success_redirects

# Start the dev server (runs at http://localhost:8000)
uvicorn main:app --reload

# Generate an Alembic migration after model changes
alembic revision --autogenerate -m "description"
alembic upgrade head
```

Install deps: `pip install -r requirements-dev.txt`

## Architecture

Self-hosted Oklahoma payroll application. FastAPI backend, Jinja2 + HTMX + Alpine.js + Tailwind frontend, SQLite + SQLAlchemy ORM.

### Shared Jinja2 instance

All routers import `templates` from **`app_templates.py`** — a single `Jinja2Templates` instance. This matters because `main.py` registers the `csrf_token` Jinja2 global on this instance. Creating a new `Jinja2Templates` per-router breaks that global.

### Auth & CSRF

- `routers/auth.py` — `get_current_user` dependency; `require_role(*roles)` factory (admin always passes, otherwise role must be in the given list) backs `require_admin` / `require_preparer` / `require_approver`, exposed as the `AdminUser` / `PreparerUser` / `ApproverUser` typed dependencies; login/logout routes
- Four roles (`models/user.py:USER_ROLES`): `admin` (superset — company/benefit/WC-code config, user management, everything below), `preparer` (employees, W-4/OK withholding, benefit enrollments, garnishments, timesheets, open pay periods, calculate draft), `approver` (approve run, void paycheck, mark paid), `read_only` (view only — no dependency needed, just doesn't satisfy any mutating route's role check)
- `routers/companies.py` intentionally stays `AdminUser`-only for all mutating routes — company/benefit-plan/WC-code config is tenant-level setup, a different risk class than routine payroll prep, so it's not preparer-accessible. Don't "fix" this to `PreparerUser` — it's deliberate. Full rationale: `plans/RBAC-PLAN.md`
- `routers/users.py` — admin-only user management (create/edit role & active flag/reset password); has a lockout guard preventing the last active admin from being demoted or deactivated
- `utils/csrf.py` — `_csrf_dep` dependency + `csrf_token_global` Jinja2 global
- Every router sets `dependencies=[Depends(get_current_user)]` at the `APIRouter` level; every mutating (POST) route also adds `current_user: AdminUser`/`PreparerUser`/`ApproverUser` + `_csrf: CsrfProtect`
- Login rate limiting: 5 attempts per 5 minutes per IP:username (in-memory, `routers/auth.py`)
- `has_role(request, *roles)` Jinja2 global in `main.py` gates template UI (buttons etc.) — admin always satisfies it; `is_admin(request)` is `has_role(request, "admin")`, kept for templates that should stay admin-only (e.g. companies). This is UX only — the router dependency is the actual security boundary.
- Security headers middleware in `main.py`: X-Frame-Options, CSP, nosniff, Referrer-Policy, HSTS (production)
- **Tests**: `conftest.py` overrides `get_current_user`, `require_admin`, `require_preparer`, `require_approver`, `_csrf_dep`, and the `is_admin`/`has_role` template globals on the `client` fixture so tests bypass auth, CSRF, and see admin UI. Auth/role-specific tests use `auth_client` (plus `admin_user`/`preparer_user`/`approver_user`/`readonly_user` fixtures, also in `conftest.py`) which does NOT override these deps, so auth runs for real — see `tests/test_auth.py`, `tests/test_roles.py`, `tests/test_users.py`.
- Password hashing uses `bcrypt` directly (not passlib — passlib is incompatible with bcrypt 4.x+)

### Tax engine

Pure Python, no ORM or HTTP side effects. Lives in `tax_engine/`. Entry point is `tax_engine/calculator.py:calculate_paycheck()`. Fully unit-tested against known IRS/OTC values.

### Payroll run flow

`PayPeriod.status`: `open → draft → approved → paid`; individual `Paycheck.status` can be `voided`.

`services/payroll_service.py` orchestrates: `calculate_payroll_run` → `approve_payroll_run` → `mark_period_paid` → `void_paycheck`. These call the tax engine and write `Paycheck` + `PaycheckLine` rows.

### Encryption

`utils/crypto.py` wraps Fernet (via `cryptography` package). Key set in `.env` as `ENCRYPTION_KEY`. Employee SSN, routing number, and account number are stored encrypted. `encrypt()` raises `RuntimeError` if `ENCRYPTION_KEY` is not configured — data is never silently dropped. `decrypt()` returns `None` if no key configured or on decryption failure.

### Audit log

`services/audit.py:log_change()` writes to `audit_log` table. Currently hooked on employee create/update and paycheck approve/void. Caller must `db.commit()` after calling (it only adds to the session).

### PDF generation

`GET /payroll/paychecks/{id}/pdf` in `routers/pay_periods.py`. Lazy-imports WeasyPrint inside the function; returns HTTP 503 if GTK runtime is missing (Windows dev machines). Renders `templates/payroll/paystub.html` via `templates.env.get_template(...).render(...)` (no `Request` object needed).

### Reports

`routers/reports.py` — 10 endpoints: payroll register, tax liability, quarterly 941, workers comp, OK withholding, W-2 export, deductions, client liabilities, new hires, plus index page. `_load_paychecks()` is the shared query helper (joinedload lines/employee/pay_period, filters voided, date-range filters). `_sum_lines()` does single-pass aggregation across all paycheck lines into a dict. W-2 export returns `StreamingResponse` with `text/csv`.

### Key env vars (`.env`)

| Var | Default | Purpose |
|-----|---------|---------|
| `DATABASE_URL` | `sqlite:///./payroll.db` | DB path |
| `ENCRYPTION_KEY` | _(empty)_ | Fernet key; generate with `Fernet.generate_key()`. Required to store SSN/bank data. |
| `SECRET_KEY` | `dev-secret-key-change-in-production` | Session signing. **Must change** — app refuses to start with default unless `DEBUG=true`. |
| `DEBUG` | `false` | Enables API docs, relaxes startup checks |
| `SESSION_HTTPS_ONLY` | `false` | Set `true` in production to restrict session cookie to HTTPS |
| `ADMIN_USERNAME` | `admin` | Seeded on first run |
| `ADMIN_PASSWORD` | `changeme` | Seeded on first run |
