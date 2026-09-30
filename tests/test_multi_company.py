"""
Per-user company (tenant) scoping, end-to-end with real auth via auth_client.

The centrepiece is TestCrossCompanyReads: every route that resolves a record
from a path parameter must 404 -- not 403, not 200 -- when that record belongs
to another payroll client.
"""
import re
from datetime import date

import pytest

from models.company import Company
from models.employee import Employee
from models.payroll import PayPeriod, Paycheck
from models.user import User
from models.user_company import UserCompany
from models.workers_comp import WorkersCompCode
from routers.auth import hash_password


# --- fixtures on auth_db (auth_client's session) --------------------------

@pytest.fixture()
def co_a(auth_db):
    co = Company(name="Alpha Co", pay_frequency="biweekly", state="OK")
    auth_db.add(co)
    auth_db.commit()
    auth_db.refresh(co)
    return co


@pytest.fixture()
def co_b(auth_db):
    co = Company(name="Beta Co", pay_frequency="biweekly", state="OK")
    auth_db.add(co)
    auth_db.commit()
    auth_db.refresh(co)
    return co


def _employee(auth_db, company, first="Emp", last="Loyee"):
    emp = Employee(
        company_id=company.id, first_name=first, last_name=last,
        employment_type="hourly", pay_rate=20.00, status="active",
        state="OK", flsa_exempt=False, hire_date=date(2025, 1, 2),
    )
    auth_db.add(emp)
    auth_db.commit()
    auth_db.refresh(emp)
    return emp


def _pay_period(auth_db, company):
    pp = PayPeriod(
        company_id=company.id, start_date=date(2026, 5, 1), end_date=date(2026, 5, 14),
        pay_date=date(2026, 5, 20), frequency="biweekly", status="open",
    )
    auth_db.add(pp)
    auth_db.commit()
    auth_db.refresh(pp)
    return pp


@pytest.fixture()
def emp_a(auth_db, co_a):
    return _employee(auth_db, co_a, "Alice", "Alpha")


@pytest.fixture()
def emp_b(auth_db, co_b):
    return _employee(auth_db, co_b, "Bob", "Beta")


@pytest.fixture()
def period_a(auth_db, co_a):
    return _pay_period(auth_db, co_a)


@pytest.fixture()
def period_b(auth_db, co_b):
    return _pay_period(auth_db, co_b)


@pytest.fixture()
def paycheck_b(auth_db, co_b, emp_b, period_b):
    pc = Paycheck(
        employee_id=emp_b.id, pay_period_id=period_b.id, status="draft",
        gross_wages=1000, total_deductions=0, total_taxes_withheld=100, net_pay=900,
    )
    auth_db.add(pc)
    auth_db.commit()
    auth_db.refresh(pc)
    return pc


@pytest.fixture()
def wc_code_b(auth_db, co_b):
    code = WorkersCompCode(
        company_id=co_b.id, ncci_code="5645", description="Carpentry",
        rate_per_100_wages=8.5,
    )
    auth_db.add(code)
    auth_db.commit()
    auth_db.refresh(code)
    return code


@pytest.fixture()
def scoped_admin(auth_db, co_a):
    """An admin with no UserCompany rows at all -- admins bypass company scope."""
    user = User(username="boss", hashed_password=hash_password("bosspass123"),
                role="admin", is_active=True)
    auth_db.add(user)
    auth_db.commit()
    auth_db.refresh(user)
    return user


@pytest.fixture()
def alpha_preparer(auth_db, co_a):
    """A preparer who may see Alpha Co and nothing else."""
    user = User(username="alpha_prep", hashed_password=hash_password("alphapass123"),
                role="preparer", is_active=True)
    auth_db.add(user)
    auth_db.commit()
    auth_db.refresh(user)
    auth_db.add(UserCompany(user_id=user.id, company_id=co_a.id))
    auth_db.commit()
    return user


@pytest.fixture()
def beta_preparer(auth_db, co_b):
    """A preparer entitled to Beta -- the positive control for leak tests."""
    user = User(username="beta_prep", hashed_password=hash_password("betapass123"),
                role="preparer", is_active=True)
    auth_db.add(user)
    auth_db.commit()
    auth_db.refresh(user)
    auth_db.add(UserCompany(user_id=user.id, company_id=co_b.id))
    auth_db.commit()
    return user


@pytest.fixture()
def orphan_user(auth_db):
    """A preparer with no company assignments at all."""
    user = User(username="orphan", hashed_password=hash_password("orphanpass123"),
                role="preparer", is_active=True)
    auth_db.add(user)
    auth_db.commit()
    auth_db.refresh(user)
    return user


def login(client, username, password):
    r = client.post("/auth/login", data={
        "username": username, "password": password, "next": "/",
    })
    assert r.status_code == 303, r.text
    return r


def csrf(client, path="/"):
    page = client.get(path)
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', page.text)
    return m.group(1) if m else ""


# --- the IDOR matrix ------------------------------------------------------

class TestCrossCompanyReads:
    """Alpha's preparer must get 404 on every Beta-owned record."""

    def _paths(self, emp_b, period_b, paycheck_b, wc_code_b, co_b):
        return [
            f"/employees/{emp_b.id}",
            f"/employees/{emp_b.id}/edit",
            f"/employees/{emp_b.id}/w4/new",
            f"/employees/{emp_b.id}/ok-withholding/new",
            f"/employees/{emp_b.id}/garnishments",
            f"/payroll/{period_b.id}",
            f"/payroll/{period_b.id}/timesheets",
            f"/payroll/paychecks/{paycheck_b.id}",
            f"/payroll/paychecks/{paycheck_b.id}/pdf",
            f"/companies/{co_b.id}",
            f"/companies/{co_b.id}/edit",
            f"/companies/{co_b.id}/benefits",
            f"/companies/{co_b.id}/wc-codes",
            f"/companies/{co_b.id}/wc-codes/{wc_code_b.id}/edit",
        ]

    def test_every_cross_company_read_is_404(
        self, auth_client, alpha_preparer, emp_b, period_b, paycheck_b, wc_code_b, co_b,
    ):
        login(auth_client, "alpha_prep", "alphapass123")
        failures = []
        for path in self._paths(emp_b, period_b, paycheck_b, wc_code_b, co_b):
            r = auth_client.get(path)
            if r.status_code == 403:
                # 403 would confirm the record exists under another client.
                failures.append((path, "403 leaks existence; want 404"))
            elif r.status_code != 404:
                failures.append((path, r.status_code))
        assert not failures, failures

    def test_beta_data_is_reachable_by_its_owner(
        self, auth_client, beta_preparer, emp_b, period_b, paycheck_b, wc_code_b, co_b,
    ):
        """Positive control for the test below.

        Without this, asserting "Beta data absent" proves nothing -- those
        responses are 404s with empty bodies, so the assertion would still pass
        if the route were renamed or the fixture never rendered the data at all.
        This pins that the markers DO appear when the viewer is entitled to them.
        """
        login(auth_client, "beta_prep", "betapass123")
        seen_company = seen_employee = False
        for path in self._paths(emp_b, period_b, paycheck_b, wc_code_b, co_b):
            r = auth_client.get(path)
            if r.status_code != 200:
                continue
            seen_company |= "Beta Co" in r.text
            seen_employee |= "Bob" in r.text
        assert seen_company, "no page rendered the company marker; control is broken"
        assert seen_employee, "no page rendered the employee marker; control is broken"

    def test_no_beta_data_in_response_bodies(
        self, auth_client, alpha_preparer, emp_b, period_b, paycheck_b, wc_code_b, co_b,
    ):
        """The negative half. Meaningful only alongside the control above."""
        login(auth_client, "alpha_prep", "alphapass123")
        for path in self._paths(emp_b, period_b, paycheck_b, wc_code_b, co_b):
            r = auth_client.get(path)
            assert "Beta Co" not in r.text, path
            assert "Bob" not in r.text, path

    def test_own_company_records_still_load(
        self, auth_client, alpha_preparer, emp_a, period_a,
    ):
        login(auth_client, "alpha_prep", "alphapass123")
        assert auth_client.get(f"/employees/{emp_a.id}").status_code == 200
        assert auth_client.get(f"/payroll/{period_a.id}").status_code == 200

    def test_admin_reaches_every_company(
        self, auth_client, scoped_admin, emp_b, period_b, co_b,
    ):
        login(auth_client, "boss", "bosspass123")
        assert auth_client.get(f"/employees/{emp_b.id}").status_code == 200
        assert auth_client.get(f"/payroll/{period_b.id}").status_code == 200
        assert auth_client.get(f"/companies/{co_b.id}").status_code == 200


class TestCrossCompanyWrites:
    def test_cannot_create_employee_in_other_company(
        self, auth_client, alpha_preparer, co_b, auth_db,
    ):
        login(auth_client, "alpha_prep", "alphapass123")
        token = csrf(auth_client, "/employees/new")
        r = auth_client.post("/employees/new", data={
            "company_id": str(co_b.id),
            "first_name": "Sneaky", "last_name": "Insert",
            "employment_type": "salaried", "pay_rate": "50000",
            "csrf_token": token,
        })
        assert r.status_code == 404
        assert auth_db.query(Employee).filter(
            Employee.first_name == "Sneaky"
        ).count() == 0

    def test_cannot_reassign_employee_into_other_company(
        self, auth_client, alpha_preparer, emp_a, co_b, auth_db,
    ):
        login(auth_client, "alpha_prep", "alphapass123")
        token = csrf(auth_client, f"/employees/{emp_a.id}/edit")
        r = auth_client.post(f"/employees/{emp_a.id}/edit", data={
            "company_id": str(co_b.id),
            "first_name": "Alice", "last_name": "Alpha",
            "employment_type": "hourly", "pay_rate": "20",
            "csrf_token": token,
        })
        assert r.status_code == 404
        auth_db.refresh(emp_a)
        assert emp_a.company_id != co_b.id

    def test_cannot_create_pay_period_in_other_company(
        self, auth_client, alpha_preparer, co_b, auth_db,
    ):
        login(auth_client, "alpha_prep", "alphapass123")
        token = csrf(auth_client, "/payroll/new")
        r = auth_client.post("/payroll/new", data={
            "company_id": str(co_b.id),
            "start_date": "2026-07-01", "end_date": "2026-07-14",
            "pay_date": "2026-07-20", "frequency": "biweekly",
            "csrf_token": token,
        })
        assert r.status_code == 404
        assert auth_db.query(PayPeriod).filter(
            PayPeriod.company_id == co_b.id,
            PayPeriod.pay_date == date(2026, 7, 20),
        ).count() == 0

    def test_cannot_book_timesheet_across_companies(
        self, auth_client, alpha_preparer, period_a, emp_b,
    ):
        """Alpha's period plus Beta's employee must not combine."""
        login(auth_client, "alpha_prep", "alphapass123")
        token = csrf(auth_client, f"/payroll/{period_a.id}")
        r = auth_client.post(f"/payroll/{period_a.id}/timesheets/{emp_b.id}", data={
            "regular_hours": "40", "csrf_token": token,
        })
        assert r.status_code == 404


class TestInScopeMismatchVsOutOfScope:
    """Out of scope -> 404 (indistinguishable from missing). In scope but the
    wrong pairing -> 422 with a form error, because both records are ones this
    user may legitimately see and it is an ordinary mistake."""

    def test_off_cycle_mismatch_is_422_for_admin(
        self, auth_client, scoped_admin, co_a, emp_b,
    ):
        login(auth_client, "boss", "bosspass123")
        token = csrf(auth_client, "/payroll/off-cycle/new")
        r = auth_client.post("/payroll/off-cycle/new", data={
            "company_id": str(co_a.id), "employee_id": str(emp_b.id),
            "pay_date": "2026-08-01", "frequency": "biweekly",
            "gross_amount": "500", "csrf_token": token,
        })
        assert r.status_code == 422
        assert "belongs to a different company" in r.text

    def test_off_cycle_out_of_scope_company_still_404(
        self, auth_client, alpha_preparer, co_b, emp_b,
    ):
        login(auth_client, "alpha_prep", "alphapass123")
        token = csrf(auth_client, "/payroll/off-cycle/new")
        r = auth_client.post("/payroll/off-cycle/new", data={
            "company_id": str(co_b.id), "employee_id": str(emp_b.id),
            "pay_date": "2026-08-01", "frequency": "biweekly",
            "gross_amount": "500", "csrf_token": token,
        })
        assert r.status_code == 404

    def test_timesheet_mismatch_is_422_for_admin(
        self, auth_client, scoped_admin, period_a, emp_b,
    ):
        login(auth_client, "boss", "bosspass123")
        token = csrf(auth_client, f"/payroll/{period_a.id}")
        r = auth_client.post(f"/payroll/{period_a.id}/timesheets/{emp_b.id}", data={
            "regular_hours": "40", "csrf_token": token,
        })
        assert r.status_code == 422


class TestDependentOptionRoutes:
    """HTMX partials that refresh the company-dependent selects."""

    def test_wc_options_scoped_to_requested_company(
        self, auth_client, scoped_admin, co_b, wc_code_b,
    ):
        login(auth_client, "boss", "bosspass123")
        r = auth_client.get(f"/employees/wc-code-options?company_id={co_b.id}")
        assert r.status_code == 200
        assert "5645" in r.text

    def test_wc_options_reject_out_of_scope_company(
        self, auth_client, alpha_preparer, co_b, wc_code_b,
    ):
        login(auth_client, "alpha_prep", "alphapass123")
        r = auth_client.get(f"/employees/wc-code-options?company_id={co_b.id}")
        assert r.status_code == 404
        assert "5645" not in r.text

    def test_employee_options_scoped_to_requested_company(
        self, auth_client, scoped_admin, co_b, emp_b,
    ):
        login(auth_client, "boss", "bosspass123")
        r = auth_client.get(f"/payroll/off-cycle/employee-options?company_id={co_b.id}")
        assert r.status_code == 200
        assert "Bob" in r.text

    def test_employee_options_cannot_enumerate_other_tenant(
        self, auth_client, alpha_preparer, co_b, emp_b,
    ):
        login(auth_client, "alpha_prep", "alphapass123")
        r = auth_client.get(f"/payroll/off-cycle/employee-options?company_id={co_b.id}")
        assert r.status_code == 404
        assert "Bob" not in r.text


class TestScopeQueryBudget:
    """Pins the per-request caching so the N-reads regression cannot return."""

    def test_user_companies_read_once_per_request(
        self, auth_client, auth_db, alpha_preparer, emp_a, period_a,
    ):
        from sqlalchemy import event

        login(auth_client, "alpha_prep", "alphapass123")

        counts = []

        def _before(conn, cursor, statement, params, context, executemany):
            if "user_companies" in " ".join(statement.split()).lower():
                counts.append(statement)

        engine = auth_db.get_bind()
        event.listen(engine, "before_cursor_execute", _before)
        try:
            for path in ("/", "/employees/", "/payroll/", "/companies/"):
                counts.clear()
                auth_client.get(path)
                assert len(counts) <= 1, (path, len(counts))
        finally:
            event.remove(engine, "before_cursor_execute", _before)


class TestCompanySwitcher:
    def test_switch_to_permitted_company(self, auth_client, alpha_preparer, co_a):
        login(auth_client, "alpha_prep", "alphapass123")
        token = csrf(auth_client, "/")
        r = auth_client.post("/companies/switch", data={
            "company_id": str(co_a.id), "next": "/employees/", "csrf_token": token,
        })
        assert r.status_code == 303
        assert r.headers["location"] == "/employees/"

    def test_switch_to_forbidden_company_rejected(
        self, auth_client, alpha_preparer, co_b,
    ):
        login(auth_client, "alpha_prep", "alphapass123")
        token = csrf(auth_client, "/")
        r = auth_client.post("/companies/switch", data={
            "company_id": str(co_b.id), "csrf_token": token,
        })
        assert r.status_code == 404
        # Session must be untouched: Beta stays unreachable afterwards.
        assert auth_client.get(f"/companies/{co_b.id}").status_code == 404

    def test_switch_rejects_offsite_next(self, auth_client, alpha_preparer, co_a):
        login(auth_client, "alpha_prep", "alphapass123")
        token = csrf(auth_client, "/")
        r = auth_client.post("/companies/switch", data={
            "company_id": str(co_a.id), "next": "//evil.example.com",
            "csrf_token": token,
        })
        assert r.headers["location"] == "/"

    def test_revoked_access_takes_effect_without_relogin(
        self, auth_client, alpha_preparer, co_a, auth_db,
    ):
        login(auth_client, "alpha_prep", "alphapass123")
        assert auth_client.get(f"/companies/{co_a.id}").status_code == 200

        auth_db.query(UserCompany).filter(
            UserCompany.user_id == alpha_preparer.id
        ).delete(synchronize_session=False)
        auth_db.commit()

        # Same session, no re-login: the stale session company_id must not be trusted.
        assert auth_client.get(f"/companies/{co_a.id}").status_code == 404
        assert auth_client.get("/employees/").status_code == 200


class TestZeroCompanyUser:
    def test_list_pages_render_empty(self, auth_client, orphan_user, co_a, emp_a):
        login(auth_client, "orphan", "orphanpass123")
        for path in ("/", "/employees/", "/payroll/", "/companies/", "/reports/"):
            r = auth_client.get(path)
            assert r.status_code == 200, (path, r.status_code)
            assert "Alice" not in r.text, path

    def test_cannot_reach_any_record(self, auth_client, orphan_user, emp_a, period_a):
        login(auth_client, "orphan", "orphanpass123")
        assert auth_client.get(f"/employees/{emp_a.id}").status_code == 404
        assert auth_client.get(f"/payroll/{period_a.id}").status_code == 404


class TestScopedLists:
    def test_employee_list_excludes_other_company(
        self, auth_client, alpha_preparer, emp_a, emp_b,
    ):
        login(auth_client, "alpha_prep", "alphapass123")
        r = auth_client.get("/employees/?company_id=all")
        assert "Alice" in r.text
        assert "Bob" not in r.text

    def test_company_list_excludes_other_company(
        self, auth_client, alpha_preparer, co_a, co_b,
    ):
        login(auth_client, "alpha_prep", "alphapass123")
        r = auth_client.get("/companies/")
        assert "Alpha Co" in r.text
        assert "Beta Co" not in r.text

    def test_pay_period_list_excludes_other_company(
        self, auth_client, alpha_preparer, period_a, period_b,
    ):
        login(auth_client, "alpha_prep", "alphapass123")
        r = auth_client.get("/payroll/?company_id=all")
        assert "Alpha Co" in r.text
        assert "Beta Co" not in r.text

    def test_garbage_company_id_falls_back_to_active_company(
        self, auth_client, alpha_preparer, emp_a, emp_b, period_a, period_b,
    ):
        """An unparseable filter is unset, not a 500 -- and never widens scope."""
        login(auth_client, "alpha_prep", "alphapass123")
        r = auth_client.get("/employees/?company_id=abc")
        assert r.status_code == 200
        assert "Alice" in r.text
        assert "Bob" not in r.text
        r = auth_client.get("/payroll/?company_id=abc")
        assert r.status_code == 200
        assert "Alpha Co" in r.text
        assert "Beta Co" not in r.text


class TestMarkNewHireReportedAccess:
    def test_out_of_scope_employee_is_404(self, auth_client, alpha_preparer, emp_b):
        login(auth_client, "alpha_prep", "alphapass123")
        token = csrf(auth_client, "/employees/")
        r = auth_client.post(f"/employees/{emp_b.id}/new-hire-reported",
                             data={"csrf_token": token})
        assert r.status_code == 404

    def test_read_only_user_is_forbidden(self, auth_client, readonly_user, emp_a):
        login(auth_client, "viewer", "viewpass")
        token = csrf(auth_client, "/employees/")
        r = auth_client.post(f"/employees/{emp_a.id}/new-hire-reported",
                             data={"csrf_token": token})
        assert r.status_code == 403
