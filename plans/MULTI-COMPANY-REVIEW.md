# Multi-Company Scoping — Review Findings

Deep-dive review of the uncommitted multi-company scoping changes (30 modified files,
10 new files) on top of `17d3243`. Reviewed 2026-09-12.

Baseline: full suite green — **410 passed**. Cross-tenant access was probed directly
against all nine `/reports/*` endpoints with a scoped preparer; every one 404s
out-of-scope and none leak into `company_id=-1`. The scoping design itself is sound;
findings below are defects around its edges.

---

## Correctness — crashes on bad input

### 1. `int(wc_code_id)` raises 500 on non-numeric input

**`routers/employees.py:49`** — new code, reachable from both `create_employee` and
`update_employee`.

```python
code = db.query(WorkersCompCode).filter(WorkersCompCode.id == int(wc_code_id)).first()
```

Confirmed by probe:

```
POST /employees/new  workers_comp_code_id=junk
ValueError: invalid literal for int() with base 10: 'junk'
```

**Fix:** parse inside `try/except ValueError` and return the existing
`"Select a workers comp code belonging to this company."` error, so a malformed id
lands on the normal 422 form path rather than a 500.

### 2. `?company_id=abc` on list routes raises 500

**`routers/employees.py:78-79`**, **`routers/pay_periods.py:53-54`**

```python
elif company_id:
    assert_company_access(current_user, int(company_id), db)
    query = query.filter(Employee.company_id == int(company_id))
```

The bare `int()` on a string query param is a pre-existing pattern, but this diff adds
a second call in front of it inside the new branch. Unparseable input should be treated
as unset (fall through to the active company) rather than crashing.

---

## Security hygiene

### 3. Promoting a user to admin leaves stale `user_companies` rows

**`routers/users.py:42`** — `_sync_company_assignments` returns early for admins:

```python
if target_user.role == "admin":
    return
```

Consequences:

- Existing grant rows survive the promotion, unaudited.
- The users list renders "All" for admins, so the stale rows are invisible in the UI.
- A later demotion back to a non-admin role re-renders the form with those boxes
  pre-checked (`assigned_company_ids` reads the stale rows) and silently restores the
  old company set.

This is the same failure mode `CLAUDE.md` deliberately closes for reactivation
("Reactivating a deactivated non-admin grants no company access … given SSN/bank data
is in scope"). Promotion should get the same treatment.

**Fix:** on promotion, delete the rows and `log_change` each deletion instead of
returning early.

### 4. Open-redirect guard misses backslash

**`routers/companies.py:45`** (and the verbatim copy it came from,
**`routers/auth.py:127`**):

```python
if not next.startswith("/") or next.startswith("//"):
    next = "/"
```

`/\evil.com` passes both checks; several browsers normalize it to `//evil.com` and
follow it off-site.

**Fix:** reject when `next[1:2] in ("/", "\\")`, or parse with `urlparse` and require
an empty netloc. Both call sites need it.

---

## Correctness — rendering

### 5. New-hires report lists every hire twice in consolidated mode

**`templates/reports/new_hires.html:33-64`**

The per-company `<ul>` groups render under `{% if consolidated and groups %}`, then the
flat `employees` table renders below unconditionally. So `company_id=-1` shows each
employee once in their company group and again in a flat table that has no company
column — exactly the undifferentiated view the other consolidated reports were written
to avoid.

**Fix:** adopt the pattern the other six reports use:

```jinja
{% set sections = groups if consolidated else [{'company': None, 'employees': employees}] %}
```

---

## Performance

### 6. `company_context` opens a second DB session per page render

**`main.py:76`, `main.py:97`**

The Jinja global opens its own `SessionLocal()` whenever
`request.state.company_context` was not stashed. `_stash_switcher`
(`routers/auth.py`) only fires on routes that declare the `ActiveCompany` dependency,
so every other authenticated page pays for it — measured 2 extra queries on a separate
connection for `/users/`, `/reports/`, `/companies/`.

It also forces `tests/conftest.py` to monkeypatch the global away, which means the real
code path is never exercised by any test.

**Fix:** populate `request.state.company_context` from something every request passes
through — `get_current_user`, or middleware — reusing the request's own session.

### 7. `accessible_companies` is not memoized

**`utils/company_scope.py:63`**

`accessible_company_ids` caches on the `User` instance, but `accessible_companies` does
not, so `SELECT companies ORDER BY name` runs three times per request on `/employees/`
and on the report routes (measured). Cache it the same way, or have routes reuse the
list `get_active_company` already resolved.

### 8. Redundant `pay_periods` query, multiplied per company group

**`routers/reports.py:218`**

`_load_paychecks` already `joinedload`s `Paycheck.pay_period`, but
`_tax_liability_rows` re-queries `PayPeriod` by id anyway — and in consolidated mode
it is called once per company group, so the redundant query fans out with tenant count.

Same shape at **`routers/reports.py:456`**: `_workers_comp_rows(db, pcs, [cid])` per
group means one employee query per company.

**Fix:** read `pc.pay_period` from the already-loaded relationship. For workers comp,
load employees once across all `company_ids` and pass the map into the helper.

---

## Low

- **`routers/auth.py:92`** — writes `session["company_id"] = None` on every request when
  no company is accessible, re-signing the session cookie on each response. Use `pop`.
- **`templates/layout.html:100`** — the switcher's `next` is `request.url.path` only, so
  switching company from a filtered report discards the query string.
- **Coverage gap** — `tests/test_multi_company.py::TestCrossCompanyReads._paths` covers
  employees, payroll and companies but no `/reports/*` path. All nine were verified
  manually during this review; nothing in the suite pins them.
- **`templates/reports/tax_liability.html`** — the grand-total strip shows only
  `total_cost` while each per-company footer shows the full breakdown.

---

## Solid

Worth keeping as-is:

- **404-not-403 for out-of-scope records**, with
  `test_beta_data_is_reachable_by_its_owner` as a positive control — without it the
  "no Beta data in body" assertion would pass against an empty 404 body and prove
  nothing.
- **`_company_ids_cache` cleared in `get_current_user`** — the SQLAlchemy identity-map
  trap (re-querying the `User` hands back the same instance, so the cache would outlive
  the request and re-open the revocation hole) is real, and the comment names it.
- **`_collapse_duplicate_codes` called in both migration directions** — makes
  upgrade/downgrade cycles idempotent instead of compounding cloned WC codes.
- **941 / W-2 / OK withholding refusing `CONSOLIDATED`** — filed per EIN, so a merged
  total reconciles to no real return.
- **Audit-logging company grants and revokes** — company access is a security boundary,
  treated like a role change.
- **`templates/employees/list.html` filter-name fix** — `status_filter`/`company_filter`
  never matched the route's `status`/`company_id` params, so those HTMX filters were
  silently dead before this change.
