# Payroll

Self-hosted payroll application for small businesses operating in Oklahoma. Handles employee management, payroll calculation, tax withholding, deductions, and compliance reporting.

## Stack

- **Backend**: FastAPI + SQLAlchemy + SQLite
- **Frontend**: Jinja2 + HTMX + Alpine.js + Tailwind CSS
- **PDF**: WeasyPrint (requires GTK on Windows — optional)

## Features

- Employee management with W-4 and Oklahoma withholding elections
- Benefit plan enrollment (health, dental, 401k, FSA/HSA) with pre-tax and post-tax deductions
- Garnishment order management (child support, creditor, tax levy, student loan)
- Full payroll run workflow: open → draft → approve → paid
- Off-cycle payroll for individual employees
- Timesheet entry for hourly and part-time employees
- Tax engine: federal (IRS Pub 15), Oklahoma (OTC tables), FICA, FUTA, SUTA, workers comp
- Pay stub PDF generation
- Reports: payroll register, tax liability, quarterly 941, workers comp audit, Oklahoma withholding, deduction/benefit summary, client liability remittance, new hire reporting, W-2 CSV export
- Terminated employee warnings (final paycheck tracking)
- Session authentication with role-based access (admin / read-only)
- Login rate limiting and security headers (CSP, HSTS, X-Frame-Options)
- CSRF protection on all mutating routes including logout
- SSN and banking info encrypted at rest (Fernet)
- Audit log for sensitive field changes

## Setup

```bash
pip install -r requirements-dev.txt

cp .env.example .env
# Edit .env — set ENCRYPTION_KEY and SECRET_KEY (see comments in the file)

uvicorn main:app --reload
```

The database is created automatically on first run. A default admin user (`admin` / `changeme`) is seeded if no users exist — change the password immediately via `ADMIN_USERNAME` / `ADMIN_PASSWORD` in `.env` before first run.

## Tests

```bash
pytest                                        # all 299 tests
pytest tests/test_auth.py                    # single file
pytest tests/test_auth.py::TestLoginLogout   # single class
```

## Tax rates (2025/2026)

| Tax | Rate |
|-----|------|
| Social Security | 6.2% employee + 6.2% employer (wage base $176,100) |
| Medicare | 1.45% + 1.45%; +0.9% additional above $200,000 |
| Federal income | IRS Publication 15 percentage method |
| Oklahoma income | OTC withholding tables (0.25%–4.75%) |
| FUTA | 0.6% net on first $7,000 wages |
| Oklahoma SUTA | Configurable rate per company |

## License

MIT
