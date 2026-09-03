# Payroll Application — Implementation Plan

## Overview

A self-hosted payroll application for small businesses operating in Oklahoma. Handles employee management, payroll calculation, tax withholding, deductions, employer contributions, and compliance reporting. Built with Python (FastAPI), HTMX, and SQLite.

---

## Tech Stack

| Layer | Choice | Rationale |
|---|---|---|
| Backend | FastAPI | Async, clean routing, auto OpenAPI docs |
| Templates | Jinja2 | Server-rendered HTML, pairs naturally with HTMX |
| Frontend | HTMX + Alpine.js | Minimal JavaScript, server-driven interactions |
| CSS | Tailwind CSS | Utility-first, no build step via CDN |
| Database | SQLite + SQLAlchemy | Simple, file-based, zero-config |
| Migrations | Alembic | Schema versioning for SQLAlchemy |
| PDF Generation | WeasyPrint | HTML→PDF, easy to style with CSS |
| Testing | pytest | Unit-test the tax engine against known tables |

---

## Domain Model

### Employee Types
- **Salaried** — fixed annual salary, divided by pay periods; FLSA exempt
- **Hourly** — rate × hours worked; overtime eligible (FLSA non-exempt)
- **Part-time** — hourly, typically no benefits; overtime eligible

### Pay Frequencies
- Weekly (52 periods/year)
- Biweekly (26 periods/year)
- Semi-monthly (24 periods/year)
- Monthly (12 periods/year)

### Earnings Types
- Regular pay
- Overtime (1.5× rate for non-exempt employees >40 hrs/week)
- Double time
- PTO / vacation pay
- Sick pay
- Holiday pay
- Bonus (supplemental wage — different federal withholding method)
- Commission
- Expense reimbursement (non-taxable)

### Deduction Types

**Pre-tax (reduce federal/state taxable wages):**
- Health insurance premium
- Dental / vision premium
- FSA contribution
- HSA contribution
- Traditional 401(k) / 403(b)

**Post-tax:**
- Roth 401(k)
- Wage garnishment
- Child support order
- Voluntary post-tax deductions

### Employer Contributions
- 401(k) / retirement plan match (e.g., 100% up to 4% of gross)
- Health insurance employer share
- HSA employer contribution

### Taxes Withheld (Employee)
- Federal income tax (IRS Publication 15, W-4 elections)
- Oklahoma state income tax (OTC withholding tables, 0.25%–4.75%)
- Social Security (6.2%, wage base $176,100 for 2025)
- Medicare (1.45%; additional 0.9% on wages over $200,000)

### Employer-Side Taxes
- FICA match — Social Security 6.2%, Medicare 1.45%
- FUTA — 6.0% on first $7,000 wages (net 0.6% after state credit)
- Oklahoma SUTA — variable rate, ~$27,000 wage base
- Workers compensation — rate per $100 wages by NCCI job class code

### Client Liabilities
- Amounts owed to third parties on behalf of employees (garnishment remittances, benefit premium payments, retirement plan deposits)

---

## Database Schema

### `companies`
```
id, name, ein, address, city, state, zip,
pay_frequency, suta_rate, workers_comp_policy_number,
created_at, updated_at
```

### `employees`
```
id, company_id, first_name, last_name,
ssn_encrypted, address, city, state, zip,
email, phone, emergency_contact,
hire_date, termination_date, status (active/terminated/on_leave),
employment_type (salaried/hourly/part_time),
flsa_exempt (bool),
pay_rate, pay_frequency,
department, job_title,
workers_comp_code_id,
direct_deposit_routing, direct_deposit_account (encrypted),
created_at, updated_at
```

### `w4_elections`
```
id, employee_id, effective_date,
filing_status (single/married/head_of_household),
multiple_jobs (bool),
dependents_amount, other_income, deductions_amount, extra_withholding,
version (2019+ form vs legacy allowances)
```

### `ok_withholding_elections`
```
id, employee_id, effective_date,
filing_status, allowances, extra_withholding
```

### `benefit_plans`
```
id, company_id, name, type (health/dental/vision/fsa/hsa/401k/etc),
employee_contribution_type (fixed/percent),
employee_contribution_amount,
employer_match_percent, employer_match_cap_percent,
pre_tax (bool)
```

### `employee_benefit_enrollments`
```
id, employee_id, benefit_plan_id, effective_date, end_date
```

### `workers_comp_codes`
```
id, ncci_code, description, rate_per_100_wages
```

### `pay_periods`
```
id, company_id, start_date, end_date, pay_date,
frequency, status (open/draft/approved/paid/closed)
```

### `timesheets`
```
id, employee_id, pay_period_id,
regular_hours, overtime_hours, double_time_hours,
pto_hours, sick_hours, holiday_hours,
submitted_at, approved_by, approved_at
```

### `paychecks`
```
id, employee_id, pay_period_id,
status (draft/approved/paid/voided),
gross_wages, total_deductions, total_taxes_withheld, net_pay,
employer_fica, employer_futa, employer_suta, employer_workers_comp,
ytd_gross, ytd_federal_tax, ytd_state_tax, ytd_fica_employee,
ytd_fica_employer, ytd_futa, ytd_suta,
check_number, paid_at, voided_at, void_reason,
created_at, approved_by, approved_at
```

### `paycheck_lines`
```
id, paycheck_id, line_type (earning/deduction/tax/employer_tax),
description, amount, is_pre_tax, is_taxable, hours, rate
```

### `client_liabilities`
```
id, company_id, pay_period_id, paycheck_id (nullable),
liability_type (garnishment/child_support/benefit_premium/401k_deposit/etc),
payee_name, amount, due_date, remitted_at, remittance_reference
```

### `audit_log`
```
id, table_name, record_id, action (insert/update/delete),
changed_by, changed_at, old_values (json), new_values (json)
```

---

## Tax Calculation Engine

The tax engine is a pure Python module with no database or HTTP side effects. Every function is independently unit-testable.

### Calculation Order (per paycheck)

1. **Gross earnings** — sum all earnings lines (regular + OT + bonuses + etc.)
2. **Pre-tax deductions** — subtract to get federal/state taxable wages
3. **Federal income tax** — IRS Publication 15 percentage method tables, using W-4 elections and pay frequency
4. **Oklahoma state income tax** — OTC withholding tables by filing status and pay period
5. **Social Security** — 6.2% up to annual wage base (check YTD accumulator)
6. **Medicare** — 1.45% flat; +0.9% additional once YTD wages exceed $200,000
7. **Post-tax deductions** — garnishments, Roth contributions, etc.
8. **Employer taxes** — FICA match, FUTA (with wage base cap), SUTA (with wage base cap), workers comp
9. **Net pay** — gross minus all employee-side deductions and taxes

### Key Constraints
- SS wage base check must use YTD wages to avoid over-withholding mid-year
- FUTA / SUTA only apply to wages under their respective annual caps
- Supplemental wages (bonuses) use 22% flat federal rate (under $1M) or aggregate method
- Garnishment orders have specific priority rules and disposable earnings limits (Consumer Credit Protection Act)

### Module Structure
```
payroll/
  tax_engine/
    __init__.py
    federal.py       # IRS withholding tables and calculations
    oklahoma.py      # OTC withholding tables and calculations
    fica.py          # SS, Medicare, employer FICA
    unemployment.py  # FUTA, SUTA
    workers_comp.py  # Workers comp premium calc
    calculator.py    # Orchestrates full paycheck calculation
    models.py        # Pure data classes (no ORM): PaycheckInput, PaycheckResult
```

---

## Application Structure

```
payroll/
  main.py                  # FastAPI app entry point
  config.py                # Settings (DB path, encryption key, etc.)
  database.py              # SQLAlchemy engine and session
  models/                  # ORM models (one file per domain)
  schemas/                 # Pydantic request/response schemas
  routers/                 # FastAPI routers
    employees.py
    pay_periods.py
    timesheets.py
    payroll_runs.py
    reports.py
    companies.py
  tax_engine/              # Pure calculation logic (see above)
  templates/               # Jinja2 HTML templates
    layout.html
    employees/
    payroll/
    reports/
  static/                  # CSS, JS, assets
  tests/
    test_federal_tax.py
    test_oklahoma_tax.py
    test_fica.py
    test_calculator.py
    test_routers/
```

---

## UI Screens

### Company Setup
- Company profile (EIN, address, pay frequency, SUTA rate)
- Benefit plan configuration
- Workers comp code management

### Employee Management
- Employee roster — filterable by type, status, department
- Employee profile — personal info, pay settings, W-4, OK withholding
- Benefit enrollments
- Garnishment / deduction orders

### Timesheet Entry (hourly/part-time)
- Grid view: employees × hours types for the current pay period
- Inline editing via HTMX
- Batch approve

### Payroll Run
1. **Open pay period** — set date range and pay date
2. **Enter timesheets** — for hourly employees
3. **Calculate (draft)** — preview all paychecks; see gross, deductions, taxes, net
4. **Review** — flag anomalies (e.g., large variance from prior period)
5. **Approve** — lock the run; paychecks become immutable
6. **Mark paid** — record payment date and check numbers
7. **Off-cycle** — manual check entry outside a regular pay period

### Paycheck Detail
- Itemized earnings, deductions, taxes, employer costs
- YTD totals
- Printable pay stub (PDF via WeasyPrint)

### Reports Hub
- Payroll register (all checks in a period)
- Tax liability summary (federal + OK + FICA + FUTA + SUTA)
- Workers comp audit report (wages by NCCI code)
- Deduction / benefit report
- Client liability remittance list
- 941 quarterly summary data
- W-2 data export (year-end)
- Oklahoma OTC withholding summary

---

## Payroll Workflow States

```
open → draft → approved → paid → closed
                    ↓
                 voided
```

- **Open** — pay period exists, timesheets can be entered
- **Draft** — tax engine has run; paychecks exist but are editable
- **Approved** — paychecks are locked; no further edits
- **Paid** — payment confirmed; check numbers recorded
- **Closed** — period archived; feeds into YTD accumulators
- **Voided** — a single check can be voided (requires reason); does not affect the pay period status

---

## Oklahoma Compliance Checklist

- [ ] State income tax withholding using current OTC tables
- [ ] SUTA reporting (Oklahoma Employment Security Commission)
- [ ] Workers comp coverage verification per employee
- [ ] New hire reporting within 20 days of hire to Oklahoma DHS
- [ ] Pay stub provided each pay period (Oklahoma requirement)
- [ ] Final paycheck on next scheduled payday upon termination
- [ ] Minimum wage compliance ($7.25/hr, mirrors federal)
- [ ] Overtime: 1.5× for non-exempt employees >40 hrs/week (FLSA)

---

## Build Phases

### Phase 1 — Foundation
- Project scaffold (FastAPI app, SQLAlchemy, Alembic)
- Database schema and ORM models
- Alembic migration baseline
- Company and employee CRUD with basic UI

### Phase 2 — Tax Engine
- Pure Python tax calculation module
- Federal withholding (IRS Publication 15 percentage method)
- Oklahoma state withholding (OTC tables)
- FICA (employee + employer), FUTA, SUTA
- Workers comp premium
- Full pytest suite with known-good scenarios

### Phase 3 — Payroll Run
- Pay period management
- Timesheet entry for hourly workers
- Full paycheck calculation (draft run)
- Review screen with variance flags
- Approve / void workflow
- YTD accumulator updates on close

### Phase 4 — Pay Stubs & PDF
- Itemized pay stub template
- WeasyPrint PDF rendering endpoint
- Email-ready (future: attach to email)

### Phase 5 — Reports
- Payroll register
- Tax liability summary
- 941 quarterly data
- Workers comp audit report
- Client liability remittance report
- W-2 data export (CSV + printable)
- Oklahoma withholding summary

### Phase 6 — Compliance & Hardening
- SSN and banking info encryption at rest
- Audit log for all sensitive field changes
- Role-based access (admin vs. read-only)
- Input validation and CSRF protection
- Session authentication

---

## Open Questions / Future Considerations

- **Multi-company support** — schema supports it; UI can be added later
- **Direct deposit file generation** — NACHA ACH file format
- **Email pay stubs** — SMTP integration
- **Benefits enrollment portal** — employee self-service
- **PTO accrual tracking** — balance management per employee
- **Multi-state employees** — out of scope initially; schema should not preclude it
- **Contractor / 1099 payments** — separate from payroll; 1099-NEC at year-end
- **Federal tax deposit reminders** — 941 semiweekly vs. monthly deposit schedule
