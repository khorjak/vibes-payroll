"""Remittance tracking (client liabilities) and check numbers."""
import re
from datetime import date
from decimal import Decimal

import pytest

from models.audit import AuditLog
from models.company import Company
from models.employee import Employee
from models.payroll import ClientLiability, PayPeriod, Paycheck
from models.user import User
from models.user_company import UserCompany
from routers.auth import hash_password
from services.payroll_service import mark_period_paid, set_check_number


def _period(db, company, status="approved", pay_date=date(2026, 5, 20)):
    pp = PayPeriod(company_id=company.id, start_date=date(2026, 5, 1), end_date=date(2026, 5, 14),
                   pay_date=pay_date, frequency="biweekly", status=status)
    db.add(pp)
    db.commit()
    return pp


def _paycheck(db, pp, employee, status="approved"):
    pc = Paycheck(employee_id=employee.id, pay_period_id=pp.id, status=status,
                  gross_wages=1000, net_pay=800)
    db.add(pc)
    db.commit()
    return pc


def _liability(db, pp, pc=None, payee="OK Child Support", amount="100.00", **kw):
    li = ClientLiability(company_id=pp.company_id, pay_period_id=pp.id,
                         paycheck_id=pc.id if pc else None, liability_type="child_support_remittance",
                         payee_name=payee, amount=Decimal(amount), **kw)
    db.add(li)
    db.commit()
    return li


def _remit(client, company, **over):
    data = {"company_id": company.id, "year": 2026, "payee_name": "OK Child Support"}
    data.update(over)
    return client.post("/reports/client-liabilities/remit", data=data)


# ── Remittance ──────────────────────────────────────────────────────────────

class TestRemit:
    def test_marks_outstanding_for_payee_only(self, client, db, company, salaried_employee):
        pp = _period(db, company)
        pc = _paycheck(db, pp, salaried_employee)
        mine = _liability(db, pp, pc)
        other_payee = _liability(db, pp, pc, payee="IRS Levy")
        r = _remit(client, company, reference="ACH 1234")
        assert r.status_code == 303
        assert "flash=remitted" in r.headers["location"]
        db.refresh(mine)
        db.refresh(other_payee)
        assert mine.remitted_at is not None
        assert mine.remittance_reference == "ACH 1234"
        assert other_payee.remitted_at is None

    def test_report_shows_remitted_amount(self, client, db, company, salaried_employee):
        pp = _period(db, company)
        pc = _paycheck(db, pp, salaried_employee)
        _liability(db, pp, pc, amount="250.00")
        _remit(client, company)
        page = client.get(f"/reports/client-liabilities?company_id={company.id}&year=2026").text
        assert "$250.00" in page
        assert "Mark Remitted" not in page  # nothing outstanding any more

    def test_already_remitted_not_overwritten(self, client, db, company, salaried_employee):
        pp = _period(db, company)
        pc = _paycheck(db, pp, salaried_employee)
        done = _liability(db, pp, pc, remittance_reference="OLD")
        done.remitted_at = date(2026, 6, 1)
        db.commit()
        fresh = _liability(db, pp, pc)
        _remit(client, company, reference="NEW")
        db.refresh(done)
        db.refresh(fresh)
        assert done.remittance_reference == "OLD"
        assert fresh.remittance_reference == "NEW"

    def test_nothing_outstanding_is_400(self, client, company):
        assert _remit(client, company).status_code == 400

    def test_draft_and_voided_paychecks_not_remitted(self, client, db, company, salaried_employee):
        pp = _period(db, company)
        draft = _liability(db, pp, _paycheck(db, pp, salaried_employee, "draft"))
        voided = _liability(db, pp, _paycheck(db, pp, salaried_employee, "voided"))
        assert _remit(client, company).status_code == 400
        db.refresh(draft)
        db.refresh(voided)
        assert draft.remitted_at is None and voided.remitted_at is None

    def test_other_year_untouched(self, client, db, company, salaried_employee):
        pp = _period(db, company, pay_date=date(2025, 12, 31))
        li = _liability(db, pp, _paycheck(db, pp, salaried_employee))
        assert _remit(client, company, year=2026).status_code == 400
        db.refresh(li)
        assert li.remitted_at is None

    def test_paycheck_less_liability_can_be_remitted(self, client, db, company):
        pp = _period(db, company)
        li = _liability(db, pp)
        assert _remit(client, company).status_code == 303
        db.refresh(li)
        assert li.remitted_at is not None

    def test_writes_audit_row(self, client, db, company, salaried_employee):
        pp = _period(db, company)
        li = _liability(db, pp, _paycheck(db, pp, salaried_employee))
        _remit(client, company, reference="R1")
        row = db.query(AuditLog).filter_by(table_name="client_liabilities", record_id=li.id).one()
        assert row.action == "update"

    def test_long_reference_rejected(self, client, db, company):
        pp = _period(db, company)
        li = _liability(db, pp)
        assert _remit(client, company, reference="x" * 101).status_code == 422
        db.refresh(li)
        assert li.remitted_at is None

    def test_consolidated_view_redirects_back_to_consolidated(self, client, db, company, salaried_employee):
        pp = _period(db, company)
        _liability(db, pp, _paycheck(db, pp, salaried_employee))
        r = _remit(client, company, view=-1)
        assert "company_id=-1" in r.headers["location"]

    def test_button_rendered_for_outstanding(self, client, db, company, salaried_employee):
        pp = _period(db, company)
        _liability(db, pp, _paycheck(db, pp, salaried_employee))
        page = client.get(f"/reports/client-liabilities?company_id={company.id}&year=2026").text
        assert "Mark Remitted" in page


# ── Check numbers ───────────────────────────────────────────────────────────

@pytest.fixture()
def two_employees(db, company, salaried_employee, hourly_employee):
    return [salaried_employee, hourly_employee]


class TestMarkPaidNumbering:
    def test_numbers_consecutively_in_paycheck_order(self, client, db, company, two_employees):
        pp = _period(db, company)
        pcs = [_paycheck(db, pp, e) for e in two_employees]
        r = client.post(f"/payroll/{pp.id}/mark-paid", data={"first_check_number": "1001"})
        assert r.status_code == 303
        for pc in pcs:
            db.refresh(pc)
        assert [pc.check_number for pc in pcs] == ["1001", "1002"]
        assert all(pc.status == "paid" for pc in pcs)

    def test_blank_first_number_leaves_checks_unnumbered(self, client, db, company, two_employees):
        pp = _period(db, company)
        pc = _paycheck(db, pp, two_employees[0])
        assert client.post(f"/payroll/{pp.id}/mark-paid", data={"first_check_number": ""}).status_code == 303
        db.refresh(pc)
        assert pc.check_number is None and pc.status == "paid"

    def test_voided_paychecks_not_numbered(self, client, db, company, two_employees):
        pp = _period(db, company)
        live = _paycheck(db, pp, two_employees[0])
        dead = _paycheck(db, pp, two_employees[1], "voided")
        client.post(f"/payroll/{pp.id}/mark-paid", data={"first_check_number": "50"})
        db.refresh(live)
        db.refresh(dead)
        assert live.check_number == "50" and dead.check_number is None

    def test_clash_blocks_whole_run(self, client, db, company, two_employees):
        earlier = _paycheck(db, _period(db, company, "paid"), two_employees[0], "paid")
        earlier.check_number = "1002"
        db.commit()
        pp = _period(db, company)
        pcs = [_paycheck(db, pp, e) for e in two_employees]
        r = client.post(f"/payroll/{pp.id}/mark-paid", data={"first_check_number": "1001"})
        assert r.status_code == 400
        assert "1002" in r.text
        db.expire_all()
        assert db.get(PayPeriod, pp.id).status == "approved"
        assert all(db.get(Paycheck, pc.id).check_number is None for pc in pcs)
        assert all(db.get(Paycheck, pc.id).status == "approved" for pc in pcs)

    @pytest.mark.parametrize("bad", ["abc", "-5", "1.5"])
    def test_non_integer_rejected(self, client, db, company, bad):
        pp = _period(db, company)
        assert client.post(f"/payroll/{pp.id}/mark-paid", data={"first_check_number": bad}).status_code == 422
        assert db.get(PayPeriod, pp.id).status == "approved"

    def test_zero_rejected(self, db, company, salaried_employee):
        pp = _period(db, company)
        _paycheck(db, pp, salaried_employee)
        with pytest.raises(ValueError):
            mark_period_paid(pp, db, 0)

    def test_same_number_ok_in_another_company(self, db, company, second_company,
                                               salaried_employee, other_employee):
        a = _paycheck(db, _period(db, company), salaried_employee)
        b = _paycheck(db, _period(db, second_company), other_employee)
        set_check_number(a, "100", db)
        set_check_number(b, "100", db)  # no clash across companies
        assert (a.check_number, b.check_number) == ("100", "100")

    def test_voided_check_number_can_be_reused(self, db, company, two_employees):
        pp = _period(db, company)
        dead = _paycheck(db, pp, two_employees[0], "voided")
        dead.check_number = "77"
        live = _paycheck(db, pp, two_employees[1])
        set_check_number(live, "77", db)
        assert live.check_number == "77"


class TestSetCheckNumberRoute:
    def _url(self, pc):
        return f"/payroll/paychecks/{pc.id}/check-number"

    def test_set_and_clear(self, client, db, company, salaried_employee):
        pc = _paycheck(db, _period(db, company), salaried_employee)
        assert client.post(self._url(pc), data={"check_number": " 4001 "}).status_code == 303
        db.refresh(pc)
        assert pc.check_number == "4001"
        client.post(self._url(pc), data={"check_number": ""})
        db.refresh(pc)
        assert pc.check_number is None

    def test_works_on_paid_paycheck(self, client, db, company, salaried_employee):
        pc = _paycheck(db, _period(db, company, "paid"), salaried_employee, "paid")
        assert client.post(self._url(pc), data={"check_number": "9"}).status_code == 303

    @pytest.mark.parametrize("status", ["draft", "voided"])
    def test_rejected_for_draft_or_voided(self, client, db, company, salaried_employee, status):
        pc = _paycheck(db, _period(db, company, "draft"), salaried_employee, status)
        assert client.post(self._url(pc), data={"check_number": "9"}).status_code == 400

    def test_duplicate_rejected(self, client, db, company, two_employees):
        pp = _period(db, company)
        first, second = (_paycheck(db, pp, e) for e in two_employees)
        client.post(self._url(first), data={"check_number": "5"})
        r = client.post(self._url(second), data={"check_number": "5"})
        assert r.status_code == 400
        db.refresh(second)
        assert second.check_number is None

    def test_resaving_own_number_is_not_a_clash(self, client, db, company, salaried_employee):
        pc = _paycheck(db, _period(db, company), salaried_employee)
        client.post(self._url(pc), data={"check_number": "5"})
        assert client.post(self._url(pc), data={"check_number": "5"}).status_code == 303

    def test_too_long_rejected(self, client, db, company, salaried_employee):
        pc = _paycheck(db, _period(db, company), salaried_employee)
        assert client.post(self._url(pc), data={"check_number": "9" * 21}).status_code == 422

    def test_audit_row_written(self, client, db, company, salaried_employee):
        pc = _paycheck(db, _period(db, company), salaried_employee)
        client.post(self._url(pc), data={"check_number": "12"})
        assert db.query(AuditLog).filter_by(table_name="paychecks", record_id=pc.id).count() == 1

    def test_shown_on_period_and_paycheck_pages(self, client, db, company, salaried_employee):
        pp = _period(db, company)
        pc = _paycheck(db, pp, salaried_employee)
        client.post(self._url(pc), data={"check_number": "8888"})
        assert "8888" in client.get(f"/payroll/{pp.id}").text
        assert "8888" in client.get(f"/payroll/paychecks/{pc.id}").text

    def test_missing_paycheck_404(self, client):
        assert client.post("/payroll/paychecks/9999/check-number", data={"check_number": "1"}).status_code == 404


# ── Roles and scope (real auth) ─────────────────────────────────────────────

def _login(client, username, password):
    assert client.post("/auth/login", data={
        "username": username, "password": password, "next": "/"}).status_code == 303


def _token(client, path):
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', client.get(path).text)
    return m.group(1) if m else ""


@pytest.fixture()
def tenant(auth_db):
    """Two companies; an approver and a preparer who may see only the first."""
    a = Company(name="Alpha Co", pay_frequency="biweekly", state="OK")
    b = Company(name="Beta Co", pay_frequency="biweekly", state="OK")
    auth_db.add_all([a, b])
    auth_db.commit()
    users = {}
    for role in ("approver", "preparer"):
        u = User(username=f"{role}_x", hashed_password=hash_password("passw0rd-123"),
                 role=role, is_active=True)
        auth_db.add(u)
        auth_db.commit()
        auth_db.add(UserCompany(user_id=u.id, company_id=a.id))
        auth_db.commit()
        users[role] = u
    return a, b


class TestRolesAndScope:
    def _beta_liability(self, auth_db, beta):
        pp = _period(auth_db, beta)
        return _liability(auth_db, pp)

    def test_preparer_cannot_remit(self, auth_client, auth_db, tenant):
        alpha, _ = tenant
        li = _liability(auth_db, _period(auth_db, alpha))
        _login(auth_client, "preparer_x", "passw0rd-123")
        data = {"company_id": alpha.id, "year": 2026, "payee_name": "OK Child Support",
                "csrf_token": _token(auth_client, "/reports/")}
        assert auth_client.post("/reports/client-liabilities/remit", data=data).status_code == 403
        auth_db.refresh(li)
        assert li.remitted_at is None

    def test_approver_cannot_remit_other_company_404(self, auth_client, auth_db, tenant):
        _, beta = tenant
        li = self._beta_liability(auth_db, beta)
        _login(auth_client, "approver_x", "passw0rd-123")
        data = {"company_id": beta.id, "year": 2026, "payee_name": "OK Child Support",
                "csrf_token": _token(auth_client, "/reports/")}
        assert auth_client.post("/reports/client-liabilities/remit", data=data).status_code == 404
        auth_db.refresh(li)
        assert li.remitted_at is None

    def test_approver_can_remit_own_company(self, auth_client, auth_db, tenant):
        alpha, _ = tenant
        li = _liability(auth_db, _period(auth_db, alpha))
        _login(auth_client, "approver_x", "passw0rd-123")
        data = {"company_id": alpha.id, "year": 2026, "payee_name": "OK Child Support",
                "csrf_token": _token(auth_client, "/reports/")}
        assert auth_client.post("/reports/client-liabilities/remit", data=data).status_code == 303
        auth_db.refresh(li)
        assert li.remitted_at is not None

    def test_preparer_cannot_set_check_number(self, auth_client, auth_db, tenant):
        alpha, _ = tenant
        emp = Employee(company_id=alpha.id, first_name="A", last_name="B", employment_type="salaried",
                       pay_rate=50000, status="active", state="OK")
        auth_db.add(emp)
        auth_db.commit()
        pc = _paycheck(auth_db, _period(auth_db, alpha), emp)
        _login(auth_client, "preparer_x", "passw0rd-123")
        r = auth_client.post(f"/payroll/paychecks/{pc.id}/check-number", data={
            "check_number": "1", "csrf_token": _token(auth_client, "/reports/")})
        assert r.status_code == 403

    @pytest.mark.parametrize("status", ["draft", "approved"])
    def test_void_button_shown_to_approver_only(self, auth_client, auth_db, tenant, status):
        # The void route is approver-only; the paycheck page offered the button to everyone.
        alpha, _ = tenant
        emp = Employee(company_id=alpha.id, first_name="A", last_name="B", employment_type="salaried",
                       pay_rate=50000, status="active", state="OK")
        auth_db.add(emp)
        auth_db.commit()
        pc = _paycheck(auth_db, _period(auth_db, alpha, status=status), emp, status=status)
        _login(auth_client, "preparer_x", "passw0rd-123")
        page = auth_client.get(f"/payroll/paychecks/{pc.id}").text
        assert "Pay Stub PDF" in page and 'id="void-panel"' not in page
        auth_client.post("/auth/logout", data={"csrf_token": _token(auth_client, "/reports/")})
        _login(auth_client, "approver_x", "passw0rd-123")
        assert 'id="void-panel"' in auth_client.get(f"/payroll/paychecks/{pc.id}").text

    def test_approver_cannot_number_other_companys_paycheck(self, auth_client, auth_db, tenant):
        _, beta = tenant
        emp = Employee(company_id=beta.id, first_name="B", last_name="B", employment_type="salaried",
                       pay_rate=50000, status="active", state="OK")
        auth_db.add(emp)
        auth_db.commit()
        pc = _paycheck(auth_db, _period(auth_db, beta), emp)
        _login(auth_client, "approver_x", "passw0rd-123")
        r = auth_client.post(f"/payroll/paychecks/{pc.id}/check-number", data={
            "check_number": "1", "csrf_token": _token(auth_client, "/reports/")})
        assert r.status_code == 404
