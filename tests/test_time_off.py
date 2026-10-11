"""PTO / sick leave accrual balances (models/leave.py, services/leave.py, /employees/{id}/time-off)."""
import re
from datetime import date
from decimal import Decimal

import pytest

from app_templates import templates
from models.audit import AuditLog
from models.employee import Employee
from models.leave import LeaveEntry, LeavePolicy
from models.payroll import Paycheck, PayPeriod, Timesheet
from services.leave import balance, balances, paycheck_leave_summary
from services.payroll_service import approve_payroll_run, calculate_payroll_run, draft_paycheck, void_paycheck


def _period(db, company, pay_date=date(2026, 5, 20), start=date(2026, 5, 1), end=date(2026, 5, 14)):
    pp = PayPeriod(company_id=company.id, start_date=start, end_date=end, pay_date=pay_date,
                   frequency="biweekly", status="open")
    db.add(pp)
    db.commit()
    return pp


def _policy(db, emp, leave_type="pto", method="per_period", rate="3.08", **kw):
    p = LeavePolicy(employee_id=emp.id, leave_type=leave_type, method=method, rate=Decimal(rate), **kw)
    db.add(p)
    db.commit()
    return p


def _adjust(db, emp, hours, when=date(2026, 1, 2), leave_type="pto"):
    db.add(LeaveEntry(employee_id=emp.id, leave_type=leave_type, entry_date=when,
                      kind="adjustment", hours=Decimal(hours), note="opening"))
    db.commit()


def _timesheet(db, emp, pp, **hours):
    db.add(Timesheet(employee_id=emp.id, pay_period_id=pp.id, **hours))
    db.commit()


def _run(db, pp, approve=True):
    calculate_payroll_run(pp, db)
    if approve:
        approve_payroll_run(pp, db)


def _entries(db, emp, kind=None):
    q = db.query(LeaveEntry).filter(LeaveEntry.employee_id == emp.id)
    return q.filter(LeaveEntry.kind == kind).all() if kind else q.all()


# ── Accrual and usage ────────────────────────────────────────────────────────

class TestAccrual:
    def test_per_period_counts_only_once_approved(self, db, company, salaried_employee):
        _policy(db, salaried_employee)
        pp = _period(db, company)
        _run(db, pp, approve=False)
        assert [e.hours for e in _entries(db, salaried_employee, "accrued")] == [Decimal("3.08")]
        assert balance(db, salaried_employee.id, "pto") == 0
        approve_payroll_run(pp, db)
        assert balance(db, salaried_employee.id, "pto") == Decimal("3.08")

    def test_per_hour_counts_worked_hours_not_time_off(self, db, company, hourly_employee):
        _policy(db, hourly_employee, method="per_hour", rate="0.05")
        _adjust(db, hourly_employee, "10")
        pp = _period(db, company)
        _timesheet(db, hourly_employee, pp, regular_hours=70, overtime_hours=10, pto_hours=8, holiday_hours=8)
        _run(db, pp)
        # 80 worked hours x 0.05 = 4.00 accrued; 8 used: 10 + 4 - 8
        assert balance(db, hourly_employee.id, "pto") == Decimal("6.00")

    def test_salaried_per_hour_uses_2080_hours_a_year(self, db, company, salaried_employee):
        _policy(db, salaried_employee, method="per_hour", rate="0.0385")
        _run(db, _period(db, company))
        assert balance(db, salaried_employee.id, "pto") == Decimal("3.08")  # 2080 / 26 x 0.0385

    def test_salaried_time_off_reduces_balance_not_pay(self, db, company, salaried_employee):
        _policy(db, salaried_employee)
        _adjust(db, salaried_employee, "40")
        pp = _period(db, company)
        _timesheet(db, salaried_employee, pp, pto_hours=16)
        _run(db, pp)
        assert balance(db, salaried_employee.id, "pto") == Decimal("27.08")
        assert db.query(Paycheck).filter_by(employee_id=salaried_employee.id).one().gross_wages == Decimal("2500.00")

    def test_pto_and_sick_are_separate(self, db, company, hourly_employee):
        _policy(db, hourly_employee, "pto", rate="2")
        _policy(db, hourly_employee, "sick", rate="1")
        pp = _period(db, company)
        _timesheet(db, hourly_employee, pp, regular_hours=72, sick_hours=8)
        _run(db, pp)
        assert balances(db, [hourly_employee.id])[hourly_employee.id] == {"pto": Decimal("2"), "sick": Decimal("-7")}

    def test_untracked_type_records_nothing(self, db, company, hourly_employee):
        _policy(db, hourly_employee, "pto")
        pp = _period(db, company)
        _timesheet(db, hourly_employee, pp, regular_hours=72, sick_hours=8)
        _run(db, pp)
        assert {e.leave_type for e in _entries(db, hourly_employee)} == {"pto"}

    def test_recalculating_replaces_draft_entries(self, db, company, hourly_employee):
        _policy(db, hourly_employee)
        pp = _period(db, company)
        _timesheet(db, hourly_employee, pp, regular_hours=72, pto_hours=8)
        calculate_payroll_run(pp, db)
        calculate_payroll_run(pp, db)
        assert len(_entries(db, hourly_employee, "accrued")) == 1
        assert len(_entries(db, hourly_employee, "used")) == 1

    def test_void_drops_the_paychecks_hours(self, db, company, hourly_employee):
        _policy(db, hourly_employee)
        pp = _period(db, company)
        _timesheet(db, hourly_employee, pp, regular_hours=72, pto_hours=8)
        _run(db, pp)
        assert balance(db, hourly_employee.id, "pto") == Decimal("-4.92")
        void_paycheck(db.query(Paycheck).one(), "wrong hours", db)
        assert balance(db, hourly_employee.id, "pto") == 0

    def test_off_cycle_accrues_nothing(self, db, company, salaried_employee):
        _policy(db, salaried_employee)
        day = date(2026, 6, 5)
        pp = _period(db, company, pay_date=day, start=day, end=day)
        draft_paycheck(salaried_employee, pp, None, db, gross_override=Decimal("500"))
        assert _entries(db, salaried_employee, "accrued") == []


class TestMaximumBalance:
    def test_accrual_stops_at_the_cap(self, db, company, salaried_employee):
        _policy(db, salaried_employee, max_balance=Decimal("5"))
        _adjust(db, salaried_employee, "4")
        _run(db, _period(db, company))
        assert balance(db, salaried_employee.id, "pto") == Decimal("5.00")
        _run(db, _period(db, company, date(2026, 6, 3), date(2026, 5, 15), date(2026, 5, 28)))
        assert len(_entries(db, salaried_employee, "accrued")) == 1  # at the cap: nothing more

    def test_hours_used_make_room(self, db, company, salaried_employee):
        _policy(db, salaried_employee, max_balance=Decimal("5"))
        _adjust(db, salaried_employee, "5")
        pp = _period(db, company)
        _timesheet(db, salaried_employee, pp, pto_hours=2)
        _run(db, pp)
        assert balance(db, salaried_employee.id, "pto") == Decimal("5.00")  # 5 - 2 + 2


class TestCarryover:
    def _setup(self, db, company, emp, since):
        _policy(db, emp, carryover_limit=Decimal("40"), carryover_since=since)
        _adjust(db, emp, "60", when=date(2025, 12, 1))
        return _period(db, company, date(2026, 1, 9), date(2025, 12, 20), date(2026, 1, 2))

    def test_hours_over_the_limit_are_forfeited_on_jan_1(self, db, company, salaried_employee):
        pp = self._setup(db, company, salaried_employee, date(2025, 6, 1))
        calculate_payroll_run(pp, db)
        calculate_payroll_run(pp, db)  # once only
        forfeits = _entries(db, salaried_employee, "forfeited")
        assert [(f.entry_date, f.hours) for f in forfeits] == [(date(2026, 1, 1), Decimal("-20"))]
        approve_payroll_run(pp, db)
        assert balance(db, salaried_employee.id, "pto") == Decimal("43.08")

    def test_a_new_limit_never_forfeits_a_past_year_end(self, db, company, salaried_employee):
        pp = self._setup(db, company, salaried_employee, date(2026, 1, 5))
        _run(db, pp)
        assert _entries(db, salaried_employee, "forfeited") == []
        assert balance(db, salaried_employee.id, "pto") == Decimal("63.08")


# ── Pages ────────────────────────────────────────────────────────────────────

def _row(page, emp):
    return page.split(f'id="ts-row-{emp.id}"', 1)[1].split("</tr>", 1)[0]


class TestTimesheetPage:
    def test_salaried_rows_record_time_off_only(self, client, db, company, salaried_employee, hourly_employee):
        pp = _period(db, company)
        page = client.get(f"/payroll/{pp.id}/timesheets").text
        salaried = _row(page, salaried_employee)
        assert 'name="pto_hours"' in salaried and 'name="sick_hours"' in salaried
        assert 'name="regular_hours"' not in salaried and 'name="holiday_hours"' not in salaried
        assert 'name="regular_hours"' in _row(page, hourly_employee)

    def test_balance_hint_turns_red_when_overdrawn(self, client, db, company, hourly_employee):
        _policy(db, hourly_employee)
        _adjust(db, hourly_employee, "6")
        pp = _period(db, company)
        r = client.post(f"/payroll/{pp.id}/timesheets/{hourly_employee.id}",
                        data={"regular_hours": "72", "pto_hours": "8"}, headers={"HX-Request": "true"})
        assert re.search(r'text-red-600">Bal 6\.00', r.text)
        r = client.post(f"/payroll/{pp.id}/timesheets/{hourly_employee.id}",
                        data={"regular_hours": "72", "pto_hours": "4"}, headers={"HX-Request": "true"})
        assert re.search(r'text-slate-400">Bal 6\.00', r.text)


class TestPolicyForm:
    def _post(self, client, emp, leave_type="pto", **data):
        return client.post(f"/employees/{emp.id}/time-off/{leave_type}/policy", data=data)

    def test_set_up_and_audit(self, client, db, hourly_employee):
        r = self._post(client, hourly_employee, method="per_hour", rate="0.0385", max_balance="120")
        assert r.status_code == 303
        p = db.query(LeavePolicy).one()
        assert (p.method, p.rate, p.max_balance, p.carryover_limit) == ("per_hour", Decimal("0.0385"), Decimal("120"), None)
        log = db.query(AuditLog).filter_by(table_name="leave_policies").one()
        assert log.action == "insert" and '"rate": "0.0385"' in log.new_values

    def test_bad_values_are_rejected_and_redisplayed(self, client, db, hourly_employee):
        r = self._post(client, hourly_employee, method="per_hour", rate="2", max_balance="-5")
        assert r.status_code == 422
        assert "fraction of an hour" in r.text and "from 0 to 10,000" in r.text
        assert 'id="pto.rate" name="rate" inputmode="decimal" value="2"' in r.text
        assert db.query(LeavePolicy).count() == 0

    def test_carryover_since_set_only_when_the_limit_changes(self, client, db, hourly_employee):
        p = _policy(db, hourly_employee, carryover_limit=Decimal("40"), carryover_since=date(2024, 1, 1))
        self._post(client, hourly_employee, method="per_period", rate="4", carryover_limit="40")
        db.refresh(p)
        assert p.carryover_since == date(2024, 1, 1) and p.rate == Decimal("4")
        self._post(client, hourly_employee, method="per_period", rate="4", carryover_limit="24")
        db.refresh(p)
        assert p.carryover_since == date.today()

    def test_stop_tracking_keeps_history(self, client, db, hourly_employee):
        _policy(db, hourly_employee)
        _adjust(db, hourly_employee, "8")
        assert self._post(client, hourly_employee, method="").status_code == 303
        assert db.query(LeavePolicy).count() == 0 and len(_entries(db, hourly_employee)) == 1

    def test_unknown_leave_type_is_404(self, client, hourly_employee):
        assert self._post(client, hourly_employee, "vacation", method="per_period", rate="1").status_code == 404


class TestAdjustForm:
    def _post(self, client, emp, **data):
        return client.post(f"/employees/{emp.id}/time-off/pto/adjust", data=data)

    def test_adjustment_is_saved_and_audited(self, client, db, hourly_employee):
        _policy(db, hourly_employee)
        r = self._post(client, hourly_employee, hours="-2.5", entry_date="2026-03-01", note="Correction")
        assert r.status_code == 303
        assert balance(db, hourly_employee.id, "pto") == Decimal("-2.5")
        assert db.query(AuditLog).filter_by(table_name="leave_entries").one().action == "insert"

    @pytest.mark.parametrize("data, field", [
        ({"hours": "0", "entry_date": "2026-03-01", "note": "x"}, "pto.hours"),
        ({"hours": "abc", "entry_date": "2026-03-01", "note": "x"}, "pto.hours"),
        ({"hours": "4", "entry_date": "", "note": "x"}, "pto.entry_date"),
        ({"hours": "4", "entry_date": "2026-03-01", "note": " "}, "pto.note"),
    ])
    def test_bad_input_is_rejected(self, client, db, hourly_employee, data, field):
        _policy(db, hourly_employee)
        r = self._post(client, hourly_employee, **data)
        assert r.status_code == 422 and f'id="{field}"' in r.text
        assert _entries(db, hourly_employee) == []

    def test_needs_a_policy(self, client, db, hourly_employee):
        r = self._post(client, hourly_employee, hours="4", entry_date="2026-03-01", note="x")
        assert r.status_code == 400


class TestDisplay:
    def test_profile_and_time_off_page(self, client, db, hourly_employee):
        _policy(db, hourly_employee)
        _adjust(db, hourly_employee, "12.5")
        profile = client.get(f"/employees/{hourly_employee.id}").text
        assert f'href="/employees/{hourly_employee.id}/time-off"' in profile and "12.50 hrs" in profile
        page = client.get(f"/employees/{hourly_employee.id}/time-off").text
        assert "12.50" in page and "+12.50" in page and "opening" in page

    def test_paycheck_shows_accrued_used_and_balance(self, client, db, company, hourly_employee):
        _policy(db, hourly_employee)
        _adjust(db, hourly_employee, "10")
        pp = _period(db, company)
        _timesheet(db, hourly_employee, pp, regular_hours=72, pto_hours=8)
        calculate_payroll_run(pp, db)
        pc = db.query(Paycheck).one()
        assert paycheck_leave_summary(db, pc) == [
            {"label": "PTO", "accrued": Decimal("3.08"), "used": Decimal("8"), "balance": Decimal("5.08")}]
        page = client.get(f"/payroll/paychecks/{pc.id}").text
        assert "Time Off (hours)" in page and "5.08" in page and "once the pay run is approved" in page
        stub = templates.env.get_template("payroll/paystub.html").render(
            paycheck=pc, earnings=[], deductions=[], employee_taxes=[], employer_taxes=[],
            employer_contributions=[], time_off=paycheck_leave_summary(db, pc))
        assert "Time Off (hours)" in stub and "5.08" in stub

    def test_no_section_without_a_policy(self, client, db, company, hourly_employee):
        pp = _period(db, company)
        _timesheet(db, hourly_employee, pp, regular_hours=80)
        calculate_payroll_run(pp, db)
        assert "Time Off (hours)" not in client.get(f"/payroll/paychecks/{db.query(Paycheck).one().id}").text


# ── Roles (real auth) ────────────────────────────────────────────────────────

def test_read_only_can_view_but_not_change(auth_client, auth_db, readonly_user):
    from models.company import Company
    from models.user_company import UserCompany
    co = Company(name="Co", pay_frequency="biweekly", state="OK")
    auth_db.add(co)
    auth_db.flush()
    emp = Employee(company_id=co.id, first_name="A", last_name="B", employment_type="hourly",
                   pay_rate=20, status="active", state="OK")
    auth_db.add(emp)
    auth_db.add(UserCompany(user_id=readonly_user.id, company_id=co.id))
    auth_db.commit()
    assert auth_client.post("/auth/login", data={"username": "viewer", "password": "viewpass",
                                                 "next": "/"}).status_code == 303
    page = auth_client.get(f"/employees/{emp.id}/time-off")
    assert page.status_code == 200 and "Set up policy" not in page.text
    token = re.search(r'name="csrf_token"\s+value="([^"]+)"', auth_client.get("/reports/").text).group(1)
    r = auth_client.post(f"/employees/{emp.id}/time-off/pto/policy",
                         data={"method": "per_period", "rate": "4", "csrf_token": token})
    assert r.status_code == 403 and auth_db.query(LeavePolicy).count() == 0
